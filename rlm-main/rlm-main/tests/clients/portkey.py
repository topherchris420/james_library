from dotenv import load_dotenv

from rlm.clients.portkey import PortkeyClient

load_dotenv()


def test_portkey_one_word_go():
    import os

    api_key = os.environ.get("PORTKEY_API_KEY", "sk-test")  # use a dummy or your test key
    model_name = "@openai/gpt-5-nano"  # or any Portkey-compatible model

    client = PortkeyClient(api_key=api_key, model_name=model_name)
    prompt = "One word, go"
    try:
        result = client.completion(prompt)
        print("Portkey response:", result)
    except Exception as e:
        print("PortkeyClient error:", e)


if __name__ == "__main__":
    test_portkey_one_word_go()
