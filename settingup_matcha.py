import os
import requests
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration from environment variables
BASE_URL = os.getenv("MATCHA_BASE_URL")
API_KEY = os.getenv("MATCHA_API_KEY")
MISSION_ID_STR = os.getenv("MATCHA_MISSION_ID")

# Validate required environment variables
required_vars = {
    "MATCHA_BASE_URL": BASE_URL,
    "MATCHA_API_KEY": API_KEY,
    "MATCHA_MISSION_ID": MISSION_ID_STR,
}

missing_vars = [var for var, value in required_vars.items() if not value]
if missing_vars:
    raise RuntimeError(f"Required environment variables are missing: {', '.join(missing_vars)}. Please set them in your .env file.")

MISSION_ID = int(MISSION_ID_STR)

headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "MATCHA-API-KEY": API_KEY,
}

def test_api_key():
    url = f"{BASE_URL}/llms?select=id,list_header,name,character_limit"
    resp = requests.get(url, headers=headers, timeout=10)

    print("Status:", resp.status_code)
    print("Body:", resp.text)

    if resp.status_code == 200:
        print("✅ API key works – you can reach Matcha API.")
    elif resp.status_code in (401, 403):
        print("❌ Unauthorized – check your MATCHA-API-KEY value.")
    else:
        print("⚠️ Unexpected error – see body above.")

def list_llms():
    url = f"{BASE_URL}/llms?select=id,list_header,name,character_limit"
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    llms = resp.json()
    print("Available LLMs:")
    for llm in llms:
        print(f"- id={llm['id']}, provider={llm['list_header']}, "
              f"name={llm['name']}, char_limit={llm['character_limit']}")
    return llms



def chat_once(prompt: str) -> str:
    url = f"{BASE_URL}/completions"
    payload = {
        "mission_id": MISSION_ID,
        "input": prompt,   # or use "messages" if you want full chat structure
    }

    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != "success":
        raise RuntimeError(f"Matcha error: {data.get('error')}")

    # grab first text block
    first_output = data["output"][0]["content"][0]["text"]
    return first_output


# Azure OpenAI configuration from environment
azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
azure_api_key = os.getenv("AZURE_OPENAI_API_KEY")
azure_model_name = os.getenv("AZURE_OPENAI_MODEL_NAME")

if azure_endpoint and azure_api_key:
    from azure.ai.inference import EmbeddingsClient
    from azure.core.credentials import AzureKeyCredential

    # For Serverless API or Managed Compute endpoints
    client = EmbeddingsClient(
        endpoint=azure_endpoint,
        credential=AzureKeyCredential(azure_api_key)
    )

    # Test Azure embedding
    try:
        client2 = EmbeddingsClient(
            endpoint=azure_endpoint,
            credential=AzureKeyCredential(azure_api_key)
        )

        response = client2.embed(
            input=["first phrase","second phrase","third phrase"],
            model=azure_model_name
        )

        for item in response.data:
            length = len(item.embedding)
            print(
                f"data[{item.index}]: length={length}, "
                f"[{item.embedding[0]}, {item.embedding[1]}, "
                f"..., {item.embedding[length-2]}, {item.embedding[length-1]}]"
            )
        print(response.usage)
    except Exception as e:
        print(f"Azure OpenAI test failed: {e}")
else:
    print("Azure OpenAI credentials not configured. Skipping embedding test.")