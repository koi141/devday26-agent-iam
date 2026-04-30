
import json
import requests
from oauthlib.oauth2.rfc6749.parameters import prepare_token_request

TOKEN_URL = "https://idcs-xxxxxxxxx.identity.oraclecloud.com:443/oauth2/v1/token"
CLIENT_ID = "xxxxxxxxxxxxxxxxxxxxxx"
CLIENT_SECRET = "<xxxxxxxxxxx>"
SCOPE = ["urn:opc:idm:__myscopes__"] 


def get_access_token() -> dict:
    body = prepare_token_request(
        grant_type="client_credentials",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scope=SCOPE,
    )

    response = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=body,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    token = get_access_token()
    print(json.dumps(token, indent=2, ensure_ascii=False))
    print("access_token:", token.get("access_token"))