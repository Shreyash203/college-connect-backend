import json
import asyncio
from typing import List
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc
from jose import JWTError, jwt
from app.core.config import settings
from app.core.dependencies import get_db
from app.core.verified_dependencies import get_current_verified_user
from app.db.models import User, StudentProfile, Conversation, Message
from app.schemas.chat import ConversationRead, MessageRead
from app.core.redis import get_redis

router = APIRouter()

@router.post("/chat/start/{target_user_id}", response_model=ConversationRead)
def start_conversation(target_user_id: int, current_user: User = Depends(get_current_verified_user), db: Session = Depends(get_db)):
    if target_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot chat with yourself.")
        
    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    conv = db.query(Conversation).filter(
        or_(
            and_(Conversation.user1_id == current_user.id, Conversation.user2_id == target_user_id),
            and_(Conversation.user1_id == target_user_id, Conversation.user2_id == current_user.id)
        )
    ).first()
    
    if not conv:
        conv = Conversation(user1_id=current_user.id, user2_id=target_user_id)
        db.add(conv)
        db.commit()
        db.refresh(conv)
        
    target_profile = db.query(StudentProfile).filter(StudentProfile.user_id == target_user_id).first()
    
    return ConversationRead(
        id=conv.id,
        user1_id=conv.user1_id,
        user2_id=conv.user2_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        other_user_id=target_user_id,
        other_user_name=target_profile.display_name if target_profile else "Unknown",
        other_user_image=target_profile.image_url if target_profile else None
    )

@router.get("/chat/conversations", response_model=List[ConversationRead])
def list_conversations(current_user: User = Depends(get_current_verified_user), db: Session = Depends(get_db)):
    convs = db.query(Conversation).filter(
        or_(Conversation.user1_id == current_user.id, Conversation.user2_id == current_user.id)
    ).order_by(desc(Conversation.updated_at)).all()
    
    res = []
    for c in convs:
        other_id = c.user2_id if c.user1_id == current_user.id else c.user1_id
        other_profile = db.query(StudentProfile).filter(StudentProfile.user_id == other_id).first()
        
        last_msg = db.query(Message).filter(Message.conversation_id == c.id).order_by(desc(Message.created_at)).first()
        
        unread_count = db.query(Message).filter(
            Message.conversation_id == c.id, 
            Message.sender_id == other_id, 
            Message.is_read == False
        ).count()
        
        res.append(ConversationRead(
            id=c.id,
            user1_id=c.user1_id,
            user2_id=c.user2_id,
            created_at=c.created_at,
            updated_at=c.updated_at,
            other_user_id=other_id,
            other_user_name=other_profile.display_name if other_profile else "Unknown",
            other_user_image=other_profile.image_url if other_profile else None,
            last_message=last_msg.content if last_msg else None,
            unread_count=unread_count
        ))
    return res

@router.get("/chat/{conversation_id}/messages", response_model=List[MessageRead])
def list_messages(
    conversation_id: int, 
    skip: int = 0, 
    limit: int = 50, 
    current_user: User = Depends(get_current_verified_user), 
    db: Session = Depends(get_db)
):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv or (conv.user1_id != current_user.id and conv.user2_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
        
    messages = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(desc(Message.created_at)).offset(skip).limit(limit).all()
    
    unread_msgs = [m for m in messages if m.sender_id != current_user.id and not m.is_read]
    for m in unread_msgs:
        m.is_read = True
    if unread_msgs:
        db.commit()
        
    return messages[::-1]

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, List[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_personal_message(self, message_json: str, user_id: int):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                await connection.send_text(message_json)

manager = ConnectionManager()

async def redis_listener(user_id: int):
    redis = await get_redis()
    pubsub = redis.pubsub()
    channel_name = f"chat:{user_id}"
    await pubsub.subscribe(channel_name)
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await manager.send_personal_message(message["data"], user_id)
    except Exception as e:
        print(f"Redis listener error for user {user_id}: {e}")
    finally:
        await pubsub.unsubscribe(channel_name)
        await pubsub.close()

@router.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise ValueError("Invalid token")
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user:
            raise ValueError("User not found")
    except Exception:
        await websocket.close(code=1008)
        return
        
    await manager.connect(user.id, websocket)
    redis_task = asyncio.create_task(redis_listener(user.id))
    redis_client = await get_redis()
    
    try:
        while True:
            data = await websocket.receive_text()
            
            if len(data) > 1200: 
                await websocket.send_text(json.dumps({"error": "Payload too large"}))
                continue
                
            payload = json.loads(data)
            content = payload.get("content", "").strip()
            conversation_id = payload.get("conversation_id")
            target_user_id = payload.get("target_user_id")
            
            if not content or len(content) > 1000:
                await websocket.send_text(json.dumps({"error": "Content invalid or exceeds 1000 characters"}))
                continue
                
            conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
            if not conv or (conv.user1_id != user.id and conv.user2_id != user.id):
                continue
                
            msg = Message(conversation_id=conversation_id, sender_id=user.id, content=content)
            db.add(msg)
            conv.updated_at = msg.created_at
            db.commit()
            db.refresh(msg)
            
            msg_data = {
                "id": msg.id,
                "conversation_id": msg.conversation_id,
                "sender_id": msg.sender_id,
                "content": msg.content,
                "is_read": msg.is_read,
                "created_at": msg.created_at.isoformat() + "Z"
            }
            msg_json = json.dumps(msg_data)
            
            await redis_client.publish(f"chat:{target_user_id}", msg_json)
            await redis_client.publish(f"chat:{user.id}", msg_json)

    except WebSocketDisconnect:
        manager.disconnect(user.id, websocket)
        redis_task.cancel()
    except Exception as e:
        manager.disconnect(user.id, websocket)
        redis_task.cancel()
        print(f"WS Error: {e}")
