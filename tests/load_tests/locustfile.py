from locust import HttpUser, task, between
import random
import string

class AuthUser(HttpUser):
    # Default host (can be overridden in the UI)
    host = "http://localhost:8000"
    
    # Short wait time to quickly trigger rate limiting
    wait_time = between(0.1, 0.5)

    def random_string(self, length=10):
        letters = string.ascii_lowercase
        return ''.join(random.choice(letters) for i in range(length))

    @task
    def login_rate_limit_test(self):
        # We will attempt to login with random credentials rapidly.
        # This should quickly hit our rate limiter (e.g. 5 requests per minute per IP).
        # We simulate multiple IPs by just letting locust hammer the same IP 
        # (since all requests come from the same machine running the test)
        payload = {
            "username": f"user_{self.random_string()}@iith.ac.in",
            "password": "wrongpassword123"
        }
        
        # FastAPI OAuth2PasswordRequestForm expects form data
        with self.client.post("/api/auth/login", data=payload, catch_response=True) as response:
            if response.status_code == 429:
                response.success()
            elif response.status_code == 401 or response.status_code == 400:
                # 401/400 means it wasn't rate limited and reached the auth logic
                response.success()
            else:
                response.failure(f"Unexpected status code: {response.status_code}")
