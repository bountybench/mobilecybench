import base64
import os
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables from .env file in the agent directory
agent_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent")
env_file = os.path.join(agent_dir, ".env")
if os.path.exists(env_file):
    load_dotenv(env_file, override=True)


def encode_image(path):
    """Encode image to base64 string for OpenAI API"""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def test_openai_responses():
    # Initialize the OpenAI client
    client = OpenAI()

    model = "gpt-5"  # You can change this model
    available_images = ["test.png", "test1.png", "test2.png"]
    image_index = 0

    print("OpenAI Responses API Tester")
    print("=" * 50)
    print(f"Using model: {model}")
    print("Type 'quit' to exit")
    print()

    while True:
        # Get user input
        prompt = input("Enter your prompt: ").strip()

        if prompt.lower() == "quit":
            print("Goodbye!")
            break

        if not prompt:
            print("Please enter a prompt or 'quit' to exit.")
            continue

        # Automatically select the next image
        current_image = available_images[image_index]
        image_index = (image_index + 1) % len(
            available_images
        )  # Loop back to 0 after test2.png

        try:

            # Build content array
            content = [{"type": "input_text", "text": prompt}]

            # Add image if it exists
            if os.path.exists(current_image):
                print(f"Adding image: {current_image}")
                b64_image = encode_image(current_image)
                data_url = f"data:image/png;base64,{b64_image}"
                content.append({"type": "input_image", "image_url": data_url})
            else:
                print(f"Warning: {current_image} not found, proceeding with text only")

            # Make API call using the Responses API
            response = client.responses.create(
                model=model, input=[{"role": "user", "content": content}]
            )

            # Print the entire response
            print("\n" + "=" * 50)
            print("FULL RESPONSE:")
            print("=" * 50)
            print(response)
            print("=" * 50)

            # Write response to file with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"openai_response_{timestamp}.txt"

            with open(filename, "w") as f:
                f.write(f"Prompt: {prompt}\n")
                f.write(f"Image: {current_image}\n")
                f.write(f"Model: {model}\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write("=" * 50 + "\n")
                f.write("Full Response:\n")
                f.write(str(response))
                f.write("\n" + "=" * 50 + "\n")

            print(f"\nResponse saved to: {filename}")

        except Exception as e:
            print(f"\nError: {e}")

        print("\n" + "-" * 50 + "\n")


if __name__ == "__main__":
    test_openai_responses()
