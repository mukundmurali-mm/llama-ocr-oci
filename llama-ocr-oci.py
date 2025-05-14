import streamlit as st
import oci
import os
import base64
import mimetypes

# --- Helper Functions ---
def is_remote_file(file_path):
    return file_path.startswith("http://") or file_path.startswith("https://")

def encode_image(file_path):
    with open(file_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode("utf-8")

def guess_mime_type(file_path):
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type or "image/jpeg"

def list_config_profiles():
    config_path = os.path.expanduser("~/.oci/config")
    profiles = ["DEFAULT"]
    if os.path.exists(config_path):
        with open(config_path) as f:
            lines = f.readlines()
        profiles = [line.strip().strip("[]") for line in lines if line.startswith("[")]
    return profiles

def list_genai_models(config, compartment_id):
    try:
        if not compartment_id:
            st.sidebar.error("Please enter a Compartment ID first")
            return {}

        # Initialize the Generative AI client
        generative_ai_client = oci.generative_ai.GenerativeAiClient(config)

        # Get list of models
        response = generative_ai_client.list_models(compartment_id=compartment_id)

        # Create mapping of model names to IDs
        model_name_to_id = {}

        for item in response.data.items:
            # Create a display name that includes the provider
            display_name = f"{item.display_name} ({item.vendor})"
            model_name_to_id[display_name] = item.id

        if not model_name_to_id:
            st.sidebar.warning("No models found in the specified compartment")

        return model_name_to_id
    except Exception as e:
        st.sidebar.error(f"Error fetching models: {str(e)}")
        return {}

# --- Streamlit UI ---
st.title("🧠 OCI Vision OCR using Generative AI")

st.sidebar.header("OCI Configuration")

# Select config profile
profiles = list_config_profiles()
selected_profile = st.sidebar.selectbox("Select OCI Config Profile", profiles)

# Enter Compartment OCID
compartment_id = st.sidebar.text_input("Enter Compartment OCID")

model_id = None
if compartment_id:
    try:
        config = oci.config.from_file("~/.oci/config", selected_profile)
        model_list = list_genai_models(config, compartment_id)
        selected_model_name = st.sidebar.selectbox("Select Vision Model", list(model_list.keys()))
        model_id = model_list[selected_model_name]

    except Exception as e:
        st.sidebar.error(f"Error fetching models: {e}")

uploaded_file = st.file_uploader("Upload an image", type=["png", "jpg", "jpeg"])

if uploaded_file and model_id:
    # Save uploaded image
    with open("temp_image.png", "wb") as f:
        f.write(uploaded_file.read())
    file_path = "temp_image.png"

    config = oci.config.from_file("~/.oci/config", selected_profile)
    endpoint = "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com"

    client = oci.generative_ai_inference.GenerativeAiInferenceClient(
        config=config,
        service_endpoint=endpoint,
        retry_strategy=oci.retry.NoneRetryStrategy(),
        timeout=(10, 240)
    )

    # Prompt
    system_prompt = (
        "Convert the provided image into Markdown format. Ensure that all content from the page is included, "
        "such as headers, footers, subtexts, images (with alt text if possible), tables, and any other elements.\n\n"
        "Requirements:\n"
        "- Output Only Markdown: Return solely the Markdown content without any additional explanations or comments.\n"
        "- No Delimiters: Do not use code fences or delimiters like ```markdown.\n"
        "- Complete Content: Do not omit any part of the page, including headers, footers, and subtext."
    )

    # Image encoding
    mime_type = guess_mime_type(file_path)
    encoded_image = encode_image(file_path)
    image_url = f"data:{mime_type};base64,{encoded_image}"

    # Build chat message
    text_content = oci.generative_ai_inference.models.TextContent(text=system_prompt)
    image_content = oci.generative_ai_inference.models.ImageContent(
        image_url=oci.generative_ai_inference.models.ImageUrl(url=image_url)
    )
    message = oci.generative_ai_inference.models.Message(role="USER", content=[text_content, image_content])

    # Chat request
    chat_request = oci.generative_ai_inference.models.GenericChatRequest(
        api_format=oci.generative_ai_inference.models.BaseChatRequest.API_FORMAT_GENERIC,
        messages=[message],
        max_tokens=1500,
        temperature=0.7,
        frequency_penalty=0,
        presence_penalty=0,
        top_p=0.85
    )

    chat_detail = oci.generative_ai_inference.models.ChatDetails(
        serving_mode=oci.generative_ai_inference.models.OnDemandServingMode(model_id=model_id),
        chat_request=chat_request,
        compartment_id=compartment_id
    )

    # Call GenAI
    with st.spinner("Analyzing image with Vision LLM..."):
        try:
            response = client.chat(chat_detail)
            markdown_output = response.data._chat_response.choices[0].message.content[0].text
            st.success("OCR complete. Markdown content below:")
            st.text_area("Extracted Markdown", markdown_output, height=400)
        except Exception as e:
            st.error(f"Error: {e}")
