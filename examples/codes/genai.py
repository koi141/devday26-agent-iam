from openai import OpenAI

client = OpenAI(
    api_key="sk-xxxxxxxxxxxxxx",
    base_url="https://inference.generativeai.ap-osaka-1.oci.oraclecloud.com/openai/v1",
    project="ocid1.generativeaiproject.oc1.ap-osaka-1.xxxxxx"
)

# Responses API
response = client.responses.create(
    model="openai.gpt-oss-120b",
    input="What is 2x2?"
)
print(response)
