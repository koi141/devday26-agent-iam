from openai import OpenAI

client = OpenAI(
    api_key="sk-xxxxxxxxxxxxx",
    base_url="https://inference.generativeai.ap-osaka-1.oci.oraclecloud.com/20231130/actions/v1",
    project="ocid1.xxxxxxxxxxxxxxx"
)

# Responses API
response = client.responses.create(
    model="openai.gpt-oss-120b",
    input="What is 2x2?"
)
print(response)
