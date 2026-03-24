"""API routes - OpenAI compatible endpoints"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from datetime import datetime
from typing import List
import json
import re
import time
from ..core.auth import verify_api_key_header
from ..core.models import ChatCompletionRequest
from ..services.generation_handler import GenerationHandler, MODEL_CONFIG
from ..core.logger import debug_logger

router = APIRouter()

# Dependency injection will be set up in main.py
generation_handler: GenerationHandler = None

def set_generation_handler(handler: GenerationHandler):
    """Set generation handler instance"""
    global generation_handler
    generation_handler = handler


def _references_supported(model_config: dict, remix_target_id: str = "", video_data: str = "") -> bool:
    """Whether the current request supports references."""
    return (
        model_config.get("type") == "video"
        and model_config.get("mode") != "video_extension"
        and not remix_target_id
        and not video_data
    )

def _extract_remix_id(text: str) -> str:
    """Extract remix ID from text

    Supports two formats:
    1. Full URL: https://sora.chatgpt.com/p/s_68e3a06dcd888191b150971da152c1f5
    2. Short ID: s_68e3a06dcd888191b150971da152c1f5

    Args:
        text: Text to search for remix ID

    Returns:
        Remix ID (s_[a-f0-9]{32}) or empty string if not found
    """
    if not text:
        return ""

    # Match Sora share link format: s_[a-f0-9]{32}
    match = re.search(r's_[a-f0-9]{32}', text)
    if match:
        return match.group(0)

    return ""

@router.get("/v1/models")
async def list_models(api_key: str = Depends(verify_api_key_header)):
    """List available models"""
    models = []

    for model_id, config in MODEL_CONFIG.items():
        description = f"{config['type'].capitalize()} generation"
        if config['type'] == 'image':
            description += f" - {config['width']}x{config['height']}"
        elif config['type'] == 'video':
            if config.get("mode") == "video_extension":
                description += f" - long video extension ({config.get('extension_duration_s', 10)}s)"
            else:
                description += f" - {config.get('orientation', 'unknown')}"
        elif config['type'] == 'avatar_create':
            description += " - create avatar from video"
        elif config['type'] == 'prompt_enhance':
            description += f" - {config['expansion_level']} ({config['duration_s']}s)"

        models.append({
            "id": model_id,
            "object": "model",
            "owned_by": "sora2api",
            "description": description
        })

    return {
        "object": "list",
        "data": models
    }

@router.post("/v1/chat/completions")
async def create_chat_completion(
    request: ChatCompletionRequest,
    api_key: str = Depends(verify_api_key_header),
    http_request: Request = None
):
    """Create chat completion (unified endpoint for image and video generation)"""
    start_time = time.time()

    try:
        # Log client request
        debug_logger.log_request(
            method="POST",
            url="/v1/chat/completions",
            headers=dict(http_request.headers) if http_request else {},
            body=request.model_dump(),
            source="Client"
        )

        # Extract prompt from messages
        if not request.messages:
            raise HTTPException(status_code=400, detail="Messages cannot be empty")

        last_message = request.messages[-1]
        content = last_message.content

        # Handle both string and array format (OpenAI multimodal)
        prompt = ""
        image_data = request.image  # Default to request.image if provided
        video_data = request.video  # Video parameter
        remix_target_id = request.remix_target_id  # Remix target ID

        if isinstance(content, str):
            # Simple string format
            prompt = content
            # Extract sora id from prompt if not already provided
            extracted_id = _extract_remix_id(prompt)
            if extracted_id:
                if not remix_target_id:
                    remix_target_id = extracted_id
        elif isinstance(content, list):
            # Array format (OpenAI multimodal)
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        prompt = item.get("text", "")
                        # Extract sora id from prompt if not already provided
                        extracted_id = _extract_remix_id(prompt)
                        if extracted_id:
                            if not remix_target_id:
                                remix_target_id = extracted_id
                    elif item.get("type") == "image_url":
                        # Extract base64 image from data URI
                        image_url = item.get("image_url", {})
                        url = image_url.get("url", "")
                        if url.startswith("data:image"):
                            # Extract base64 data from data URI
                            if "base64," in url:
                                image_data = url.split("base64,", 1)[1]
                            else:
                                image_data = url
                    elif item.get("type") == "video_url":
                        # Extract video from video_url
                        video_url = item.get("video_url", {})
                        url = video_url.get("url", "")
                        if url.startswith("data:video") or url.startswith("data:application"):
                            # Extract base64 data from data URI
                            if "base64," in url:
                                video_data = url.split("base64,", 1)[1]
                            else:
                                video_data = url
                        else:
                            # It's a URL, pass it as-is (will be downloaded in generation_handler)
                            video_data = url
        else:
            raise HTTPException(status_code=400, detail="Invalid content format")

        # Validate model
        if request.model not in MODEL_CONFIG:
            raise HTTPException(status_code=400, detail=f"Invalid model: {request.model}")

        # Check if this is a video model
        model_config = MODEL_CONFIG[request.model]
        is_video_model = model_config["type"] in ["video", "avatar_create"]

        if request.references is not None and not _references_supported(model_config, remix_target_id or "", video_data or ""):
            raise HTTPException(
                status_code=400,
                detail="references are only supported for standard video and storyboard generation",
            )
        if request.references is not None and _references_supported(model_config, remix_target_id or "", video_data or ""):
            try:
                if generation_handler and generation_handler.reference_service:
                    await generation_handler.reference_service.validate_reference_ids(request.references)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        # For video models with video parameter, we need streaming
        if is_video_model and (video_data or remix_target_id):
            if not request.stream:
                # Non-streaming mode: only check availability
                result = None
                async for chunk in generation_handler.handle_generation_with_retry(
                    model=request.model,
                    prompt=prompt,
                    image=image_data,
                    video=video_data,
                    remix_target_id=remix_target_id,
                    references=request.references,
                    stream=False
                ):
                    result = chunk

                if result:
                    duration_ms = (time.time() - start_time) * 1000
                    response_data = json.loads(result)
                    debug_logger.log_response(
                        status_code=200,
                        headers={"Content-Type": "application/json"},
                        body=response_data,
                        duration_ms=duration_ms,
                        source="Client"
                    )
                    return JSONResponse(content=response_data)
                else:
                    duration_ms = (time.time() - start_time) * 1000
                    error_response = {
                        "error": {
                            "message": "Availability check failed",
                            "type": "server_error",
                            "param": None,
                            "code": None
                        }
                    }
                    debug_logger.log_response(
                        status_code=500,
                        headers={"Content-Type": "application/json"},
                        body=error_response,
                        duration_ms=duration_ms,
                        source="Client"
                    )
                    return JSONResponse(
                        status_code=500,
                        content=error_response
                    )

        # Handle streaming
        if request.stream:
            async def generate():
                try:
                    async for chunk in generation_handler.handle_generation_with_retry(
                        model=request.model,
                        prompt=prompt,
                        image=image_data,
                        video=video_data,
                        remix_target_id=remix_target_id,
                        references=request.references,
                        stream=True
                    ):
                        yield chunk
                except Exception as e:
                    # Try to parse structured error (JSON format)
                    error_data = None
                    try:
                        error_data = json.loads(str(e))
                    except:
                        pass

                    # Return OpenAI-compatible error format
                    if error_data and isinstance(error_data, dict) and "error" in error_data:
                        # Structured error (e.g., unsupported_country_code)
                        error_response = error_data
                    else:
                        # Generic error
                        error_response = {
                            "error": {
                                "message": str(e),
                                "type": "server_error",
                                "param": None,
                                "code": None
                            }
                        }
                    error_chunk = f'data: {json.dumps(error_response)}\n\n'
                    yield error_chunk
                    yield 'data: [DONE]\n\n'

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"
                }
            )
        else:
            # Non-streaming response (availability check only)
            result = None
            async for chunk in generation_handler.handle_generation_with_retry(
                model=request.model,
                prompt=prompt,
                image=image_data,
                video=video_data,
                remix_target_id=remix_target_id,
                references=request.references,
                stream=False
            ):
                result = chunk

            if result:
                duration_ms = (time.time() - start_time) * 1000
                response_data = json.loads(result)
                debug_logger.log_response(
                    status_code=200,
                    headers={"Content-Type": "application/json"},
                    body=response_data,
                    duration_ms=duration_ms,
                    source="Client"
                )
                return JSONResponse(content=response_data)
            else:
                # Return OpenAI-compatible error format
                duration_ms = (time.time() - start_time) * 1000
                error_response = {
                    "error": {
                        "message": "Availability check failed",
                        "type": "server_error",
                        "param": None,
                        "code": None
                    }
                }
                debug_logger.log_response(
                    status_code=500,
                    headers={"Content-Type": "application/json"},
                    body=error_response,
                    duration_ms=duration_ms,
                    source="Client"
                )
                return JSONResponse(
                    status_code=500,
                    content=error_response
                )

    except HTTPException as e:
        duration_ms = (time.time() - start_time) * 1000
        error_response = {
            "error": {
                "message": e.detail,
                "type": "invalid_request_error" if e.status_code == 400 else "server_error",
                "param": None,
                "code": None
            }
        }
        debug_logger.log_error(
            error_message=str(e.detail),
            status_code=e.status_code,
            response_text=str(e.detail),
            source="Client"
        )
        debug_logger.log_response(
            status_code=e.status_code,
            headers={"Content-Type": "application/json"},
            body=error_response,
            duration_ms=duration_ms,
            source="Client"
        )
        return JSONResponse(status_code=e.status_code, content=error_response)

    except Exception as e:
        # Return OpenAI-compatible error format
        duration_ms = (time.time() - start_time) * 1000
        error_response = {
            "error": {
                "message": str(e),
                "type": "server_error",
                "param": None,
                "code": None
            }
        }
        debug_logger.log_error(
            error_message=str(e),
            status_code=500,
            response_text=str(e),
            source="Client"
        )
        debug_logger.log_response(
            status_code=500,
            headers={"Content-Type": "application/json"},
            body=error_response,
            duration_ms=duration_ms,
            source="Client"
        )
        return JSONResponse(
            status_code=500,
            content=error_response
        )
