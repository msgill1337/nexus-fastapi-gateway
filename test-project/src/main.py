from fastapi import FastAPI, HTTPException, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from openai import AsyncAzureOpenAI, BadRequestError
from typing import Optional, List, Dict
from tiktoken import encoding_for_model
import logging
import time, json
from datetime import datetime
import redis
import secrets
import uuid
import os
# Optional: Load environment variables from .env file if python-dotenv is installed
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv not installed, environment variables must be set manually
    pass
from presidio_anonymizer import AnonymizerEngine
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer.entities import RecognizerResult, OperatorConfig
from azure.ai.contentsafety import ContentSafetyClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.contentsafety.models import TextCategory, AnalyzeTextOptions

# ============================================================================
# Configuration from Environment Variables
# ============================================================================

# Azure Content Safety Configuration
AZURE_CONTENT_SAFETY_ENDPOINT = os.getenv("AZURE_CONTENT_SAFETY_ENDPOINT")
AZURE_CONTENT_SAFETY_KEY = os.getenv("AZURE_CONTENT_SAFETY_KEY")

# Azure OpenAI Configuration
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")

# Redis Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")  # Optional

# Logging Configuration
LOG_FILE = os.getenv("LOG_FILE", "api.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Cost Configuration (USD per 1K tokens)
INPUT_COST_PER_1K = float(os.getenv("INPUT_COST_PER_1K", "0.00015"))
OUTPUT_COST_PER_1K = float(os.getenv("OUTPUT_COST_PER_1K", "0.0006"))

# Rate Limiting Configuration
RATE_LIMIT_TOKENS = int(os.getenv("RATE_LIMIT_TOKENS", "1000"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "3600"))

# Validate required environment variables
if not AZURE_CONTENT_SAFETY_ENDPOINT:
    raise ValueError("AZURE_CONTENT_SAFETY_ENDPOINT environment variable is required")
if not AZURE_CONTENT_SAFETY_KEY:
    raise ValueError("AZURE_CONTENT_SAFETY_KEY environment variable is required")
if not AZURE_OPENAI_ENDPOINT:
    raise ValueError("AZURE_OPENAI_ENDPOINT environment variable is required")
if not AZURE_OPENAI_API_KEY:
    raise ValueError("AZURE_OPENAI_API_KEY environment variable is required")

# ============================================================================
# Initialize Components
# ============================================================================

#Initialize the presidio engines
anonimizeEngine = AnonymizerEngine()
analyzeEngine = AnalyzerEngine()

#Initialize the Azure AI content safety client
content_safety_client = ContentSafetyClient(
    endpoint=AZURE_CONTENT_SAFETY_ENDPOINT,
    credential=AzureKeyCredential(AZURE_CONTENT_SAFETY_KEY)
)

# Configure logging
logging.basicConfig(
    filename=LOG_FILE,
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Initialize FastAPI app
app = FastAPI()

# Initialize Redis connection
redis_config = {
    "host": REDIS_HOST,
    "port": REDIS_PORT,
    "decode_responses": True
}
if REDIS_PASSWORD:
    redis_config["password"] = REDIS_PASSWORD
r = redis.Redis(**redis_config)

# Security setup for Bearer token authentication
security = HTTPBearer()

# Initialize Azure OpenAI client
client = AsyncAzureOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_API_KEY,
    api_version=AZURE_OPENAI_API_VERSION
)

class Message(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    messages: List[Message]
    model: str
    max_tokens: Optional[int] = 1000
    temperature: Optional[float] = 1.0

class CostEstimation(BaseModel):
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float

# User management models
class UserCreate(BaseModel):
    name: str

class UserResponse(BaseModel):
    user_id: str
    name: str
    api_key: str
    created_at: str

class UserListResponse(BaseModel):
    users: List[UserResponse]

# Redis user storage keys
USER_KEY_PREFIX = "user:"
API_KEY_PREFIX = "api_key:"
USERS_SET_KEY = "users:all"

# User management functions
def generate_api_key() -> str:
    """Generate a secure API key"""
    return secrets.token_urlsafe(32)

def get_user_by_api_key(api_key: str) -> Optional[Dict]:
    """Retrieve user information by API key from Redis"""
    try:
        user_id = r.get(f"{API_KEY_PREFIX}{api_key}")
        if not user_id:
            return None
        
        user_data = r.hgetall(f"{USER_KEY_PREFIX}{user_id}")
        if not user_data:
            return None
        
        return {
            "user_id": user_data.get("user_id"),
            "name": user_data.get("name"),
            "api_key": user_data.get("api_key"),
            "created_at": user_data.get("created_at")
        }
    except Exception as e:
        logging.error(f"Error retrieving user by API key: {e}")
        return None

def create_user(name: str) -> Dict:
    """Create a new user and store in Redis"""
    try:
        user_id = str(uuid.uuid4())
        api_key = generate_api_key()
        created_at = datetime.now().isoformat()
        
        # Store user data as hash
        user_key = f"{USER_KEY_PREFIX}{user_id}"
        r.hset(user_key, mapping={
            "user_id": user_id,
            "name": name,
            "api_key": api_key,
            "created_at": created_at
        })
        
        # Create API key to user_id mapping
        r.set(f"{API_KEY_PREFIX}{api_key}", user_id)
        
        # Add to users set for easy listing
        r.sadd(USERS_SET_KEY, user_id)
        
        return {
            "user_id": user_id,
            "name": name,
            "api_key": api_key,
            "created_at": created_at
        }
    except Exception as e:
        logging.error(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail="Failed to create user")

def list_users() -> List[Dict]:
    """List all users from Redis"""
    try:
        user_ids = r.smembers(USERS_SET_KEY)
        users = []
        
        for user_id in user_ids:
            user_data = r.hgetall(f"{USER_KEY_PREFIX}{user_id}")
            if user_data:
                users.append({
                    "user_id": user_data.get("user_id"),
                    "name": user_data.get("name"),
                    "api_key": user_data.get("api_key"),
                    "created_at": user_data.get("created_at")
                })
        
        return sorted(users, key=lambda x: x.get("created_at", ""), reverse=True)
    except Exception as e:
        logging.error(f"Error listing users: {e}")
        raise HTTPException(status_code=500, detail="Failed to list users")

def revoke_user(user_id: str) -> bool:
    """Revoke a user by removing them from Redis"""
    try:
        user_data = r.hgetall(f"{USER_KEY_PREFIX}{user_id}")
        if not user_data:
            return False
        
        api_key = user_data.get("api_key")
        
        # Remove API key mapping
        if api_key:
            r.delete(f"{API_KEY_PREFIX}{api_key}")
        
        # Remove user data
        r.delete(f"{USER_KEY_PREFIX}{user_id}")
        
        # Remove from users set
        r.srem(USERS_SET_KEY, user_id)
        
        return True
    except Exception as e:
        logging.error(f"Error revoking user: {e}")
        return False

# Authentication dependency
async def verify_api_key(credentials: HTTPAuthorizationCredentials = Security(security)) -> Dict:
    """Verify API key from Bearer token"""
    api_key = credentials.credentials
    
    user = get_user_by_api_key(api_key)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


@app.post("/chat/completions")
async def chat_completions(request: ChatCompletionRequest, current_user: Dict = Depends(verify_api_key)):

    try:
        r.ping()
        start_time = time.time()

        enc = encoding_for_model(request.model)
        input_rate = INPUT_COST_PER_1K
        output_rate = OUTPUT_COST_PER_1K

        messages_dict = [{"role": msg.role, "content": msg.content} for msg in request.messages]

        cleaned_messages_dict = []
        pii_info = {}
        #Run the data through Presidio's Engines

        #Analyze the data for sensitive info
        for msg in request.messages:
            analyzer_results = analyzeEngine.analyze(text=msg.content, entities=["PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", "US_SSN", "CREDIT_CARD", "LOCATION"], language='en')

            #Log PII detection event
            if analyzer_results:
                pii_detected= [{"type": r.entity_type, "score": r.score} for r in analyzer_results]
                logging.info(f"PII detected and redacted: {pii_detected}")
                pii_info = {
                    "detected" : True,
                    "entities_redacted" : [r.entity_type for r in analyzer_results]
                }

                #Track PII metrics by entity type
                for result in analyzer_results:
                    r.incr(f"metrics:pii:{result.entity_type}")

            #Anonymize the data
            anonimizer_result = anonimizeEngine.anonymize(text=msg.content, analyzer_results = analyzer_results,
            operators={
                "PERSON": OperatorConfig("replace", {"new_value": "REDACTED-NAME"}),
                "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "REDACTED-PHONE_NUMBER"}),
                "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "REDACTED-EMAIL"}),
                "US_SSN": OperatorConfig("replace", {"new_value": "REDACTED-SSN"}),
                "CREDIT_CARD": OperatorConfig("replace", {"new_value": "REDACTED-CREDIT_CARD"}),
                "LOCATION": OperatorConfig("replace", {"new_value": "REDACTED-LOCATION"}),
            }
            )

            #Run the data through Azure AI Content Safety
            request_for_safety = AnalyzeTextOptions(text=anonimizer_result.text)

            safety_response = content_safety_client.analyze_text(request_for_safety)

            hate_result = next((item for item in safety_response.categories_analysis if item.category == TextCategory.HATE), None)
            self_harm_result = next((item for item in safety_response.categories_analysis if item.category == TextCategory.SELF_HARM), None)
            sexual_result = next((item for item in safety_response.categories_analysis if item.category == TextCategory.SEXUAL), None)
            violence_result = next((item for item in safety_response.categories_analysis if item.category == TextCategory.VIOLENCE), None)

            if ((hate_result and hate_result.severity >= 4) or
                (self_harm_result and self_harm_result.severity >= 4) or
                (sexual_result and sexual_result.severity >= 4) or
                (violence_result and violence_result.severity >= 4)):

                # Track which categories violated
                if hate_result and hate_result.severity >= 4:
                    r.incr("metrics:content_safety:HATE")
                if self_harm_result and self_harm_result.severity >= 4:
                    r.incr("metrics:content_safety:SELF_HARM")
                if sexual_result and sexual_result.severity >= 4:
                    r.incr("metrics:content_safety:SEXUAL")
                if violence_result and violence_result.severity >= 4:
                    r.incr("metrics:content_safety:VIOLENCE")

                #Log the Content Safety Violation
                logging.warning(f"Content Safety violation detected: {safety_response}")

                raise HTTPException(
                    status_code=400,
                    detail="Content violates safety policies and cannot be processed"
                )
            
            cleaned_messages_dict.append({"role": msg.role, "content": anonimizer_result.text})

        num_tokens = 0
        for msg in messages_dict:
            num_tokens += len(enc.encode(msg["content"]))
            num_tokens += len(enc.encode(msg["role"]))
            num_tokens += 4
        num_tokens += 3

        #Redis logging - use authenticated user_id
        user_id = current_user["user_id"]
        token_key = f"user:{user_id}:tokens"

        if not r.exists(token_key):
            r.set(token_key, 0)
            r.expire(token_key, RATE_LIMIT_WINDOW_SECONDS)

        current_tokens = int(r.get(token_key) or 0)

        if ((current_tokens + num_tokens) >= RATE_LIMIT_TOKENS):
            raise HTTPException(status_code=429, detail=f"Rate limit exceeded. Tokens used: {current_tokens}, Requested: {num_tokens}, Time to reset {r.ttl(token_key)}")
        else:
            r.incrby(token_key, num_tokens)
            try:
                response= await client.chat.completions.create(
                    model=request.model,
                    messages=cleaned_messages_dict,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature
                )
            except BadRequestError as e:
                error_detail = e.response.json() if hasattr(e, 'response') else str(e)

                logging.warning(f"Azure OpenAI blocked request: {error_detail}")

                r.incr("metrics:azure_blocked_requests")

                raise HTTPException(
                    status_code=400,
                    detail="Request blocked by Azure OpenAI content policies"
                )

            #Cost estimation
            total_cost = (num_tokens / 1000 * input_rate) + (response.usage.completion_tokens / 1000 * output_rate)

            costs = CostEstimation(
                input_cost_usd = (num_tokens / 1000 * input_rate),
                output_cost_usd = (response.usage.completion_tokens / 1000 * output_rate),
                total_cost_usd = total_cost
            )
            duration = time.time() - start_time

            log_entry = {
                "local_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "azure_timestamp": datetime.fromtimestamp(response.created).strftime("%Y-%m-%d %H:%M:%S"),
                "model": request.model,
                "tokens": response.usage.total_tokens,
                "cost": costs.total_cost_usd,
                "duration_seconds": duration
            }

            logging.info(f"API Request: {json.dumps(log_entry)}")

            #Track total requests
            r.incr("metrics:total_requests")

            #Track total tokens
            r.incrby("metrics:total_tokens", response.usage.total_tokens)

            #Track total cost
            cost_in_cents = int(total_cost * 100000)
            r.incrby("metrics:total_cost_micro_usd", cost_in_cents)



            return {
                "sent_prompt": cleaned_messages_dict,
                "pii_detection": pii_info,
                "azure_response": response.model_dump(),
                "estimated_prompt_tokens" : num_tokens,
                "estimated_costs": costs,
                "rate_limit_info": {
                    "tokens_used": current_tokens + num_tokens,
                    "tokens_limit": RATE_LIMIT_TOKENS,
                    "tokens_remaining": RATE_LIMIT_TOKENS - (current_tokens + num_tokens),
                    "reset_in_seconds": r.ttl(token_key)
                }
            }
    except redis.ConnectionError:
        return {"error": "Failed to reach the Redis server"}

@app.get("/metrics")
def get_metrics():
    try:
        total_requests = int(r.get("metrics:total_requests") or 0)
        total_tokens = int(r.get("metrics:total_tokens") or 0)
        total_cost_micro = int(r.get("metrics:total_cost_micro_usd") or 0)
        total_cost_usd = total_cost_micro / 100000 
        azure_blocked_requests = int(r.get("metrics:azure_blocked_requests") or 0)

        # PII metrics
        pii_metrics = {
            "PERSON": int(r.get("metrics:pii:PERSON") or 0),
            "PHONE_NUMBER": int(r.get("metrics:pii:PHONE_NUMBER") or 0),
            "EMAIL_ADDRESS": int(r.get("metrics:pii:EMAIL_ADDRESS") or 0),
            "LOCATION": int(r.get("metrics:pii:LOCATION") or 0)
        }

        # Content Safety metrics
        content_safety_metrics = {
            "HATE": int(r.get("metrics:content_safety:HATE") or 0),
            "SELF_HARM": int(r.get("metrics:content_safety:SELF_HARM") or 0),
            "SEXUAL": int(r.get("metrics:content_safety:SEXUAL") or 0),
            "VIOLENCE": int(r.get("metrics:content_safety:VIOLENCE") or 0)
        }

        return {
            "overview": {
                "total_requests": total_requests,
                "total_tokens": total_tokens,
                "total_cost_usd": round(total_cost_usd, 6),
                "azure_blocked_requests": azure_blocked_requests
            },
            "pii_detections": pii_metrics,
            "content_safety_violations": content_safety_metrics,
        }

    except redis.ConnectionError:
        raise HTTPException(status_code=503, detail="Metrics unavailable - Redis conneciton failed.")

# Admin endpoints for user management
@app.post("/admin/users", response_model=UserResponse, status_code=201)
async def create_user_endpoint(user_data: UserCreate, admin_user: Dict = Depends(verify_api_key)):
    """
    Create a new user. Requires admin authentication (any valid API key can create users).
    Returns the user with API key (show this only once).
    """
    try:
        user = create_user(user_data.name)
        logging.info(f"User created: {user['user_id']} by admin: {admin_user['user_id']}")
        return UserResponse(**user)
    except Exception as e:
        logging.error(f"Failed to create user: {e}")
        raise HTTPException(status_code=500, detail="Failed to create user")

@app.get("/admin/users", response_model=UserListResponse)
async def list_users_endpoint(admin_user: Dict = Depends(verify_api_key)):
    """
    List all users. Requires admin authentication.
    Note: API keys are shown for all users. In production, consider masking them.
    """
    try:
        users = list_users()
        return UserListResponse(users=[UserResponse(**user) for user in users])
    except Exception as e:
        logging.error(f"Failed to list users: {e}")
        raise HTTPException(status_code=500, detail="Failed to list users")

@app.delete("/admin/users/{user_id}", status_code=200)
async def revoke_user_endpoint(user_id: str, admin_user: Dict = Depends(verify_api_key)):
    """
    Revoke a user by user_id. Requires admin authentication.
    This will invalidate the user's API key and remove them from the system.
    """
    try:
        if not revoke_user(user_id):
            raise HTTPException(status_code=404, detail="User not found")
        
        logging.info(f"User revoked: {user_id} by admin: {admin_user['user_id']}")
        return {"message": f"User {user_id} has been revoked successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Failed to revoke user: {e}")
        raise HTTPException(status_code=500, detail="Failed to revoke user")

@app.get("/")
def root():
    return {"message": "Welcome to Nexus AI Gateway! Use Bearer token authentication for API access."}