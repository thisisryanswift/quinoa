import keyring

from quinoa.config import config


def test_config_keyring():
    print("Testing Config with Keyring...")

    # Set a dummy key
    test_key = "test_api_key_123"
    print(f"Setting API key: {test_key}")
    config.set("api_key", test_key)

    # Verify it's in keyring
    stored_key = keyring.get_password("quinoa", "gemini_api_key")
    print(f"Key in keyring: {stored_key}")

    if stored_key == test_key:
        print("SUCCESS: Key stored in keyring")
    else:
        print("FAILURE: Key not found in keyring")

    # Verify config.get() retrieves it
    retrieved_key = config.get("api_key")
    print(f"config.get('api_key'): {retrieved_key}")

    if retrieved_key == test_key:
        print("SUCCESS: Config retrieved key from keyring")
    else:
        print("FAILURE: Config failed to retrieve key")

    # Clean up
    print("Cleaning up...")
    config.set("api_key", "")
    stored_key_after = keyring.get_password("quinoa", "gemini_api_key")
    if stored_key_after is None:
        print("SUCCESS: Key deleted from keyring")
    else:
        print("FAILURE: Key still in keyring")


if __name__ == "__main__":
    test_config_keyring()
