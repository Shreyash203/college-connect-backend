import json
import asyncio
from typing import List
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc, func
from sqlalchemy.exc import IntegrityError
from app.core.dependencies import AuthenticatedUser, decode_access_token, get_db
from app.core.verified_dependencies import get_current_verified_user
from app.db.models import User, StudentProfile, Conversation, Message, Notification
from app.schemas.chat import ConversationRead, MessageRead
from app.db.session import SessionLocal
from app.core.redis import get_redis

router = APIRouter()

@router.post("/chat/start/{target_user_id}", response_model=ConversationRead)
def start_conversation(target_user_id: int, current_user: AuthenticatedUser = Depends(get_current_verified_user), db: Session = Depends(get_db)):
    if target_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot chat with yourself.")
        
    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    u1, u2 = min(current_user.id, target_user_id), max(current_user.id, target_user_id)

    conv = db.query(Conversation).filter(
        Conversation.user1_id == u1,
        Conversation.user2_id == u2
    ).first()
    
    if not conv:
        conv = Conversation(user1_id=u1, user2_id=u2)
        try:
            db.add(conv)
            db.commit()
            db.refresh(conv)
        except IntegrityError:
            db.rollback()
            conv = db.query(Conversation).filter(
                Conversation.user1_id == u1,
                Conversation.user2_id == u2
            ).first()
            if not conv:
                raise HTTPException(status_code=500, detail="Could not create conversation.")
        
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
def list_conversations(current_user: AuthenticatedUser = Depends(get_current_verified_user), db: Session = Depends(get_db)):
    convs = db.query(Conversation).filter(
        or_(Conversation.user1_id == current_user.id, Conversation.user2_id == current_user.id)
    ).order_by(desc(Conversation.updated_at)).all()
    
    if not convs:
        return []
        
    conv_ids = [c.id for c in convs]
    other_ids = list({c.user2_id if c.user1_id == current_user.id else c.user1_id for c in convs})
    
    # 1. Batch fetch all participant profiles
    profiles = {
        p.user_id: p for p in db.query(StudentProfile).filter(StudentProfile.user_id.in_(other_ids)).all()
    } if other_ids else {}
    
    # 2. Batch fetch unread counts grouped by conversation
    unread_counts = dict(
        db.query(Message.conversation_id, func.count(Message.id))
        .filter(
            Message.conversation_id.in_(conv_ids),
            Message.sender_id != current_user.id,
            Message.is_read == False
        )
        .group_by(Message.conversation_id)
        .all()
    ) if conv_ids else {}
    
    # 3. Batch fetch latest message for each conversation
    latest_msg_ids_subq = (
        db.query(func.max(Message.id).label("max_id"))
        .filter(Message.conversation_id.in_(conv_ids))
        .group_by(Message.conversation_id)
        .subquery()
    )
    latest_messages = {
        m.conversation_id: m.content
        for m in db.query(Message).filter(Message.id.in_(db.query(latest_msg_ids_subq.c.max_id))).all()
    } if conv_ids else {}
    
    res = []
    for c in convs:
        other_id = c.user2_id if c.user1_id == current_user.id else c.user1_id
        other_profile = profiles.get(other_id)
        
        res.append(ConversationRead(
            id=c.id,
            user1_id=c.user1_id,
            user2_id=c.user2_id,
            created_at=c.created_at,
            updated_at=c.updated_at,
            other_user_id=other_id,
            other_user_name=other_profile.display_name if other_profile else "Unknown",
            other_user_image=other_profile.image_url if other_profile else None,
            last_message=latest_messages.get(c.id),
            unread_count=unread_counts.get(c.id, 0)
        ))
    return res

@router.get("/chat/{conversation_id}/messages", response_model=List[MessageRead])
def list_messages(
    conversation_id: int, 
    skip: int = 0, 
    limit: int = 50, 
    current_user: AuthenticatedUser = Depends(get_current_verified_user),
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
        self.redis_listener_task: asyncio.Task | None = None

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        
        if self.redis_listener_task is None or self.redis_listener_task.done():
            self.redis_listener_task = asyncio.create_task(redis_listener())

    def disconnect(self, user_id: int, websocket: WebSocket):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
            if not self.active_connections and self.redis_listener_task:
                task = self.redis_listener_task
                self.redis_listener_task = None
                if not task.done():
                    task.cancel()

    async def send_personal_message(self, message_json: str, user_id: int):
        if user_id in self.active_connections:
            dead_connections = []
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_text(message_json)
                except Exception:
                    dead_connections.append(connection)
            for dead in dead_connections:
                self.disconnect(user_id, dead)

manager = ConnectionManager()

async def redis_listener():
    redis = await get_redis()
    pubsub = redis.pubsub()
    try:
        await pubsub.psubscribe("chat:*")
        async for message in pubsub.listen():
            if message["type"] == "pmessage":
                channel = message["channel"]
                if not channel.startswith("chat:"):
                    continue
                try:
                    user_id = int(channel.removeprefix("chat:"))
                except ValueError:
                    continue
                await manager.send_personal_message(message["data"], user_id)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"Redis chat listener error: {e}")
    finally:
        try:
            await pubsub.punsubscribe("chat:*")
            await pubsub.close()
        except Exception:
            pass

@router.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    try:
        user_auth_id = decode_access_token(token).id
    except Exception:
        await websocket.close(code=1008)
        return
        
    await manager.connect(user_auth_id, websocket)
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
            
            if not content or len(content) > 1000:
                await websocket.send_text(json.dumps({"error": "Content invalid or exceeds 1000 characters"}))
                continue
                
            with SessionLocal() as db:
                conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
                if not conv or (conv.user1_id != user_auth_id and conv.user2_id != user_auth_id):
                    continue
                
                # Derive recipient safely from conversation
                target_user_id = conv.user2_id if conv.user1_id == user_auth_id else conv.user1_id
                
                msg = Message(conversation_id=conversation_id, sender_id=user_auth_id, content=content)
                db.add(msg)
                conv.updated_at = msg.created_at
                db.commit()
                db.refresh(msg)
                
                # Send Notification to target user
                sender_profile = db.query(StudentProfile).filter(StudentProfile.user_id == user_auth_id).first()
                sender_name = sender_profile.display_name if sender_profile else "Someone"
                
                existing_notif = db.query(Notification).filter(
                    Notification.user_id == target_user_id,
                    Notification.is_read == False,
                    Notification.message == f"You have a new message from {sender_name} 💬"
                ).first()
                
                if not existing_notif:
                    notif = Notification(
                        user_id=target_user_id,
                        message=f"You have a new message from {sender_name} 💬",
                        link=f"/messages?conversationId={conversation_id}"
                    )
                    db.add(notif)
                    db.commit()
                
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
            await redis_client.publish(f"chat:{user_auth_id}", msg_json)

    except WebSocketDisconnect:
        manager.disconnect(user_auth_id, websocket)
    except Exception as e:
        manager.disconnect(user_auth_id, websocket)
        print(f"WS Error: {e}")
