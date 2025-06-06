import gradio as gr
import os
import tempfile
import logging
from podcastfy.client import generate_podcast
from dotenv import load_dotenv
import json
import urllib.request
import sys
import mimetypes
import time
import random

# Define constants for directories
DATA_DIR = "/var/www/html/data/"
TRANSCRIPT_DIR = "/var/www/html/data/transcripts/"
AUDIO_DIR = "/var/www/html/data/audio/"
DATA_URL = "https://podcastify-files.ifork.eu/"


# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def get_api_key(key_name, ui_value):
    return ui_value if ui_value else os.getenv(key_name)

def get_wrapper_auth():
    return os.getenv("WRAPPER_AUTH")

def generatePrompt(
    input_params,
    podcast_name,
    podcast_tagline,
    input_text,
    prompt_params
    ):
    # Constants
    LONGFORM_INSTRUCTIONS = """
                                Additional Instructions:
                                    1. Provide extensive examples and real-world applications
                                    2. Include detailed analysis and multiple perspectives
                                    3. Use the "yes, and" technique to build upon points
                                    4. Incorporate relevant anecdotes and case studies
                                    5. Balance detailed explanations with engaging dialogue
                                    6. Maintain consistent voice throughout the extended discussion
                                    7. Generate a long conversation - output max_output_tokens tokens
                            """

    COMMON_INSTRUCTIONS = """
                                Keep the Podcast conversation in CONTEXT.
                                Continue the natural flow of conversation. Follow-up on the very previous point/question without repeating topics or points already discussed!
                                Hence, the transition should be smooth and natural. Avoid abrupt transitions.
                                Make sure the first to speak is different from the previous speaker. Look at the last tag in CONTEXT to determine the previous speaker.
                                If last tag in CONTEXT is <Person1>, then the first to speak now should be <Person2>.
                                If last tag in CONTEXT is <Person2>, then the first to speak now should be <Person1>.
                                This is a live conversation without any breaks.
                                Hence, avoid statemeents such as "we'll discuss after a short break.  Stay tuned" or "Okay, so, picking up where we left off".
                            """

    # Enhance the prompt_params
    prompt_params = {}

    prompt_params["word_count"] = input_params.get("word_count", 2000)
    prompt_params["conversation_style"] = input_params.get("conversation_style", "engaging,fast-paced,enthusiastic".split(','))
    prompt_params["roles_person1"] = input_params.get("roles_person1", "host")
    prompt_params["roles_person2"] = input_params.get("roles_person2", "expert guest")
    prompt_params["dialogue_structure"] = input_params.get("dialogue_structure", "question-answer,discussion,summary".split(','))

    podcast_name= podcast_name if podcast_name else "Podcastfy"
    podcast_tagline = podcast_tagline if podcast_tagline else ""
    prompt_params["input_text"] = input_text
    user_instructions = prompt_params.get("user_instructions", "") + LONGFORM_INSTRUCTIONS
    prompt_params["instruction"] = f"""
            ALWAYS START THE CONVERSATION GREETING THE AUDIENCE: Welcome to {podcast_name} - {podcast_tagline}.
            You are generating the Introduction part of a long podcast conversation. Afterwards you should continue the conversation naturally.
            For the closing part, make concluding remarks in a podcast conversation format and END THE CONVERSATION GREETING THE AUDIENCE WITH PERSON1 ALSO SAYING A GOOD BYE MESSAGE.
            Make sure to follow the following instructions: {COMMON_INSTRUCTIONS}.
            [[MAKE SURE TO FOLLOW THESE INSTRUCTIONS OVERRIDING THE PROMPT TEMPLATE IN CASE OF CONFLICT: {user_instructions}]]
            """
    return prompt_params

def process_inputs(
    text_input,
    urls_input,
    pdf_files,
    image_files,
    gemini_key,
    openai_key,
    elevenlabs_key,
    word_count,
    conversation_style,
    roles_person1,
    roles_person2,
    dialogue_structure,
    podcast_name,
    podcast_tagline,
    tts_model,
    creativity_level,
    user_instructions,
    voices,
    is_mock,
    request_id,
    callback_url,
    language
):
    try:
        # Unique identfier time based
        logger.info("Starting podcast generation process")
        logger.info("Param " + json.dumps({
            "text_input": text_input,
            "urls_input": urls_input,
            "pdf_files": pdf_files,
            "image_files": image_files,
            "gemini_key": gemini_key,
            "openai_key": openai_key,
            "elevenlabs_key": elevenlabs_key,
            "word_count": word_count,
            "conversation_style": conversation_style,
            "roles_person1": roles_person1,
            "roles_person2": roles_person2,
            "dialogue_structure": dialogue_structure,
            "podcast_name": podcast_name,
            "podcast_tagline": podcast_tagline,
            "tts_model": tts_model,
            "creativity_level": creativity_level,
            "user_instructions": user_instructions,
            "voices": voices,
            "is_mock": is_mock,
            "request_id": request_id,
            "callback_url": callback_url,
            "language": language
        }, indent=4) )

        # API key handling
        logger.debug("Setting API keys")
        os.environ["GEMINI_API_KEY"] = get_api_key("GEMINI_API_KEY", gemini_key)

        if tts_model == "openai":
            logger.debug("Setting OpenAI API key")
            if not openai_key and not os.getenv("OPENAI_API_KEY"):
                raise ValueError("OpenAI API key is required when using OpenAI TTS model")
            os.environ["OPENAI_API_KEY"] = get_api_key("OPENAI_API_KEY", openai_key)

        if tts_model == "elevenlabs":
            logger.debug("Setting ElevenLabs API key")
            if not elevenlabs_key and not os.getenv("ELEVENLABS_API_KEY"):
                raise ValueError("ElevenLabs API key is required when using ElevenLabs TTS model")
            os.environ["ELEVENLABS_API_KEY"] = get_api_key("ELEVENLABS_API_KEY", elevenlabs_key)

        SLACK_BOT_TOKEN = get_api_key("SLACK_BOT_TOKEN", "")
        SLACK_CHANNEL_ID = get_api_key("SLACK_CHANNEL_ID", "")

        requestId = request_id
        file_group = str(int(time.time())) + "_" + str(random.randint(1000, 9999))
        if not requestId:
            requestId = file_group

        # parse is_mock
        if not is_mock:
            is_mock = "No"


        if isinstance(is_mock, str) and (is_mock.lower() == "promptonly"):
            is_mock = "PromptOnly"
        elif isinstance(is_mock, str) and (is_mock.lower() == "transcript2voice"):
            is_mock = "Transcript2Voice"
        elif isinstance(is_mock, str) and (is_mock.lower() == "false" or is_mock.lower() == "no" or is_mock.lower() == "0"):
            is_mock = "No"
        elif isinstance(is_mock, str) and (is_mock.lower() == "true" or is_mock.lower() == "yes" or is_mock.lower() == "1"):
            is_mock = "Yes"
        else:
            is_mock = "Transcript"

        # Parse voices
        if not voices:
            voices = "George, Daniel"

        voices = voices.split(',')
        logger.debug(f"Voices: {voices}")
        if len(voices) == 2:
            question_voice = voices[0].strip()
            answer_voice = voices[1].strip()
        elif len(voices) == 1:
            question_voice = voices[0].strip()
            answer_voice = voices[0].strip()
        else:
            question_voice = "George"
            answer_voice = "Daniel"

        question_voice = question_voice.replace(" ", "");
        answer_voice = answer_voice.replace(" ", "");

        # Process URLs
        urls = [url.strip() for url in urls_input.split('\n') if url.strip()]
        logger.debug(f"Processed URLs: {urls}")

        temp_files = []
        temp_dirs = []

        # Handle PDF files
        if pdf_files is not None and len(pdf_files) > 0:
            logger.info(f"Processing {len(pdf_files)} PDF files")
            pdf_temp_dir = tempfile.mkdtemp()
            temp_dirs.append(pdf_temp_dir)

            for i, pdf_file in enumerate(pdf_files):
                pdf_path = os.path.join(pdf_temp_dir, f"input_pdf_{i}.pdf")
                temp_files.append(pdf_path)

                with open(pdf_path, 'wb') as f:
                    f.write(pdf_file)
                urls.append(pdf_path)
                logger.debug(f"Saved PDF {i} to {pdf_path}")

        # Handle image files
        image_paths = []
        if image_files is not None and len(image_files) > 0:
            logger.info(f"Processing {len(image_files)} image files")
            img_temp_dir = tempfile.mkdtemp()
            temp_dirs.append(img_temp_dir)

            for i, img_file in enumerate(image_files):
                # Get file extension from the original name in the file tuple
                original_name = img_file.orig_name if hasattr(img_file, 'orig_name') else f"image_{i}.jpg"
                extension = original_name.split('.')[-1]

                logger.debug(f"Processing image file {i}: {original_name}")
                img_path = os.path.join(img_temp_dir, f"input_image_{i}.{extension}")
                temp_files.append(img_path)

                try:
                    # Write the bytes directly to the file
                    with open(img_path, 'wb') as f:
                        if isinstance(img_file, (tuple, list)):
                            f.write(img_file[1])  # Write the bytes content
                        else:
                            f.write(img_file)     # Write the bytes directly
                    image_paths.append(img_path)
                    logger.debug(f"Saved image {i} to {img_path}")
                except Exception as e:
                    logger.error(f"Error saving image {i}: {str(e)}")
                    raise

        # Prepare conversation config
        logger.debug("Preparing conversation config")
        conversation_config = {
            "max_num_chunks": 100,
            "word_count": word_count,
            "conversation_style": conversation_style.split(','),
            "roles_person1": roles_person1,
            "roles_person2": roles_person2,
            "dialogue_structure": dialogue_structure.split(','),
            "podcast_name": podcast_name,
            "podcast_tagline": podcast_tagline,
            "creativity": creativity_level,
            "user_instructions": user_instructions,
            "text_to_speech": {
                "default_tts_model": "elevenlabs",
                "output_directories": {
                    "transcripts": "data/transcripts",
                    "audio": "data/audio"
                },
                "elevenlabs": {
                    "default_voices": {
                        "question": question_voice,
                        "answer": answer_voice
                    },
                    "model": "eleven_multilingual_v2"
                },
                "audio_format": "mp3",
                "temp_audio_dir": "data/audio/tmp/",
                "ending_message": ""
            },
            "content_generator": {
                "langchain_tracing_v2": False
            },
            "output_language": language,
            "is_mock": is_mock,
            "is_prompt_only": is_mock == "PromptOnly"
        }

        # Generate podcast
        logger.info("Calling generate_podcast function")
        logger.debug(f"URLs: {urls}")
        logger.debug(f"Image paths: {image_paths}")
        logger.debug(f"Text input present: {'Yes' if text_input else 'No'}")


        mock_flag = "[MOCK RUN]"
        if (is_mock == "PromptOnly"):
            mock_flag = "[PROMPT ONLY RUN]"
        elif (is_mock == "Transcript2Voice"):
            mock_flag = "[TRANSCRIPT TO VOICE RUN]"
        elif (is_mock == "No"):
            mock_flag = "[ACTUAL RUN]"
        elif (is_mock == "Transcript"):
            mock_flag = "[TRANSCRIPT ONLY]"

        send_files_to_slack(requestId, file_group, f"[{requestId}][{mock_flag}][BEGIN]", json.dumps({
            "is_mock": is_mock,
            "urls": urls,
            "text_input": text_input,
            "image_paths": image_paths,
            "tts_model": tts_model,
            "conversation_config": conversation_config
        }, indent=4) + "\n```\n", None, None, SLACK_BOT_TOKEN, SLACK_CHANNEL_ID)

        result = {}
        transcript_file = None
        audio_file = None
        prompt_file = None
        if (is_mock == "Transcript2Voice") :
            # Q: How may I get epoch timestamp in python?
            # A: You can use time.time() function to get the current epoch timestamp in python.
            transcript_file = f"{TRANSCRIPT_DIR}transcript_{file_group}.txt"
            with open(transcript_file, "w") as f:
                f.write(user_instructions)

            _result = generate_podcast(
                urls=urls if urls else None,
                text=text_input if text_input else None,
                image_paths=image_paths if image_paths else None,
                tts_model=tts_model,
                conversation_config=conversation_config,
                transcript_file=transcript_file
            )
            if isinstance(_result, str):
                audio_file = _result
            else:
                result = _result
                audio_file = _result["audio_file"]

            audio_file = os.path.abspath(audio_file)
            result["audio_file"] = audio_file
            result["transcript_file"] = transcript_file

        elif is_mock == "Yes":
            transcript_file = f"{TRANSCRIPT_DIR}transcript_eb3b9b19d81949f999680679c6e30bb0.txt"
            audio_file = f"{AUDIO_DIR}podcast_768bee6fe8884dd3bb606d0556612b13.mp3"
            result = {
                "audio_file": audio_file,
                "transcript_file": transcript_file
            }
        elif is_mock == "Transcript" or is_mock == "No":
            transcript_file = f"{TRANSCRIPT_DIR}transcript_{file_group}.txt"
            _result = generate_podcast(
                urls=urls if urls else None,
                text=text_input if text_input else None,
                image_paths=image_paths if image_paths else None,
                tts_model=tts_model,
                conversation_config=conversation_config,
                transcript_only=True,
                longform=word_count > 5000
            )
            if isinstance(_result, str):
                transcript_file = _result
            else:
                result = _result
                transcript_file = _result["transcript_file"]
            transcript_file = os.path.abspath(transcript_file)
            transcript_file_new = f"{TRANSCRIPT_DIR}transcript_{file_group}.txt"
            os.rename(transcript_file, transcript_file_new)
            transcript_file = transcript_file_new
            result["transcript_file"] = transcript_file

            if is_mock == "Transcript":
                audio_file = None
            else:
                _result = generate_podcast(
                    urls=urls if urls else None,
                    text=text_input if text_input else None,
                    image_paths=image_paths if image_paths else None,
                    tts_model=tts_model,
                    conversation_config=conversation_config,
                    transcript_file=transcript_file
                )
                if isinstance(_result, str):
                    audio_file = _result
                else:
                    audio_file = _result["audio_file"]

                audio_file = os.path.abspath(audio_file)
                # rename the audio_file to include the request id and move the file to the public directory
                audio_file_new = f"{AUDIO_DIR}podcast_{file_group}.mp3"
                os.rename(audio_file, audio_file_new)
                audio_file = audio_file_new
                result["audio_file"] = audio_file
        elif is_mock == "PromptOnly" or is_mock == "No":
            _result = generate_podcast(
                urls=urls if urls else None,
                text=text_input if text_input else None,
                image_paths=image_paths if image_paths else None,
                tts_model=tts_model,
                conversation_config=conversation_config,
                transcript_only=True,
                longform=word_count > 5000
            )
            if isinstance(_result, str):
                prompt_content = _result
            else:
                prompt_content = _result["prompt"]

            prompt_details = json.loads(prompt_content)
            text_input = prompt_details["input_text"];
            prompt_content = generatePrompt(conversation_config, podcast_name, podcast_tagline, text_input, prompt_details)

            transcript_file = None
            audio_file = None
            prompt_file = f"{TRANSCRIPT_DIR}prompt_{file_group}.json"
            with open(prompt_file, "w") as f:
                f.write(json.dumps(prompt_content))
            logger.info(f"Prompt file created: {prompt_file}")
            prompt_file = os.path.abspath(prompt_file)


        logger.info(f"Podcast generation completed => {audio_file}")

        # Cleanup
        logger.debug("Cleaning up temporary files")
        for file_path in temp_files:
            if os.path.exists(file_path):
                os.unlink(file_path)
                logger.debug(f"Removed temp file: {file_path}")
        for dir_path in temp_dirs:
            if os.path.exists(dir_path):
                os.rmdir(dir_path)
                logger.debug(f"Removed temp directory: {dir_path}")

        http_audio_file = ""
        http_transcript_file = ""

        if audio_file:
            http_audio_file = audio_file.replace(DATA_DIR, DATA_URL)

        if transcript_file:
            http_transcript_file = transcript_file.replace(DATA_DIR, DATA_URL)

        if prompt_file:
            http_transcript_file = prompt_file.replace(DATA_DIR, DATA_URL)

        send_files_to_slack(requestId, file_group, f"{requestId}\t{mock_flag}[COMPLETED]", json.dumps({
            "is_mock": is_mock,
            "urls": urls,
            "text_input": text_input,
            "image_paths": image_paths,
            "tts_model": tts_model,
            "conversation_config": conversation_config,
            "result": result,
            "http_audio_file": http_audio_file,
            "http_transcript_file": http_transcript_file
        }, indent=4) + "\n```\n", audio_file, transcript_file, SLACK_BOT_TOKEN, SLACK_CHANNEL_ID)

        if callback_url:
            # HTTP POST to callback URL with the transcript and audio file using public URLs

            logger.info(f"HTTP Audio File: {http_audio_file}")
            logger.info(f"HTTP Transcript File: {http_transcript_file}")

            # Prepare the data payload for the callback
            payload = {
                "result": "success",
                "request_id": requestId,
                "audio_file": http_audio_file,
                "transcript_file": http_transcript_file,
                "is_mock": is_mock,
                "extras": {
                    "conversation_config": conversation_config,
                    "input_params": {
                        "text_input": text_input,
                        "urls_input": urls_input,
                        "pdf_files": pdf_files,
                        "image_files": image_files,
                        "gemini_key": gemini_key,
                        "openai_key": openai_key,
                        "elevenlabs_key": elevenlabs_key,
                        "word_count": word_count,
                        "conversation_style": conversation_style,
                        "roles_person1": roles_person1,
                        "roles_person2": roles_person2,
                        "dialogue_structure": dialogue_structure,
                        "podcast_name": podcast_name,
                        "podcast_tagline": podcast_tagline,
                        "tts_model": tts_model,
                        "creativity_level": creativity_level,
                        "user_instructions": user_instructions,
                        "voices": voices,
                        "is_mock": is_mock,
                        "request_id": request_id,
                        "callback_url": callback_url,
                        "language": language
                    }
                }
            }

            # Convert the payload to JSON bytes
            data = json.dumps(payload).encode("utf-8")

            # Create a request with the required headers:
            # - Content-Type set to application/json
            request = urllib.request.Request(
                callback_url,
                data=data,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Authorization": get_wrapper_auth()
                },
                method="POST"
            )

            # Send the request
            try:
                with urllib.request.urlopen(request) as response:
                    response_data = response.read().decode("utf-8")
                    parsed = json.loads(response_data)

                    if parsed.get("ok"):
                        logger.info("Callback sent successfully.")
                    else:
                        logger.error(f"Error sending callback: {parsed}")
            except Exception as e:
                import traceback
                trace = traceback.format_exc()
                logger.error(f"[SEND CALLBACK] Exception occurred: {e}\t{trace}")

        return audio_file

    except Exception as e:
        logger.error(f"Error in process_inputs: {str(e)}", exc_info=True)
        send_text_to_slack(f"[{requestId}][{mock_flag}][ERROR]\t{str(e)}", SLACK_BOT_TOKEN, SLACK_CHANNEL_ID)
        # Cleanup on error
        for file_path in temp_files:
            if os.path.exists(file_path):
                os.unlink(file_path)
        for dir_path in temp_dirs:
            if os.path.exists(dir_path):
                os.rmdir(dir_path)
        return str(e)

def send_text_to_slack(text, SLACK_BOT_TOKEN, SLACK_CHANNEL_ID):
    """
    Sends the given text as a message to the specified Slack channel using
    only Python's built-in libraries (no requests, no slack_sdk).
    """
    url = "https://slack.com/api/chat.postMessage"


    # Prepare the data payload for Slack
    payload = {
        "channel": SLACK_CHANNEL_ID,
        "text": text
    }

    # Convert the payload to JSON bytes
    data = json.dumps(payload).encode("utf-8")

    # Create a request with the required headers:
    # - Authorization with the Bearer token
    # - Content-Type set to application/json
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
            "Content-Type": "application/json; charset=utf-8"
        },
        method="POST"
    )

    # Send the request
    try:
        with urllib.request.urlopen(request) as response:
            response_data = response.read().decode("utf-8")
            parsed = json.loads(response_data)

            if parsed.get("ok"):
                print("Message sent successfully.")
            else:
                print(f"Error sending message: {parsed}")
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        print(f"[SEND TO SLACK] Exception occurred: {e}\t{trace}")

# Send to Slack the Result files (Audio and Transcript)
def send_files_to_slack(uuid, file_group, initial_comment, input_params, audio_filepath, transcript_filepath, SLACK_BOT_TOKEN, SLACK_CHANNEL_ID):
    """Uploads audio and transcript to Slack in a single message."""
    #  Store input_params in a tmp file that should be also sent
    input_params_file_path = os.path.abspath(f"data/input_params_{file_group}.json")
    with open(input_params_file_path, "w") as input_params_file:
        input_params_file.write(input_params)

    try:
        # 1. Get upload URLs for both files
        upload_urls = {}
        file_ids = {}
        files = {}

        files["input"] = input_params_file_path

        if audio_filepath is not None:
            files["audio"] = audio_filepath

        if transcript_filepath is not None:
            files["transcript"] = transcript_filepath

        for filetype in files:
            filepath = files[filetype]
            print(f"Check file: {filepath}\t{filetype}")
            if not os.path.exists(filepath):
                continue

            url_external_url = "https://slack.com/api/files.getUploadURLExternal"
            url_external_data = urllib.parse.urlencode({
                "filename": os.path.basename(filepath),
                "length": os.path.getsize(filepath)
            }).encode("utf-8")

            url_external_request = urllib.request.Request(
                url_external_url, data=url_external_data,
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}, method="POST"
            )

            with urllib.request.urlopen(url_external_request) as url_external_response:
                url_external_data = json.loads(url_external_response.read().decode("utf-8"))

            if not url_external_data.get("ok"):
                raise Exception(f"Error getting upload URL for {filetype}: {url_external_data}")

            upload_urls[filetype] = url_external_data["upload_url"]
            file_ids[filetype] = url_external_data["file_id"]

        # 2. PUT file content to upload URLs
        for filetype in files:
            filepath = files[filetype]
            if not os.path.exists(filepath):
                continue

            with open(filepath, "rb") as f:
                file_content = f.read()

            print(f"Send to Slack: Uploading {filetype} to URL {upload_urls[filetype]} from {filepath}. File content length: {len(file_content)}")
            upload_request = urllib.request.Request(
                upload_urls[filetype], data=file_content, method="POST"
            )

            with urllib.request.urlopen(upload_request) as upload_response:
                if upload_response.getcode() != 200:  # Check HTTP status code
                    raise Exception(f"{filetype.capitalize()} upload failed with status code: {upload_response.getcode()}")


        # 3. files.completeUploadExternal (Combine in one request)
        complete_url = "https://slack.com/api/files.completeUploadExternal"
        files_data = []


        for filetype in files:
            if filetype in file_ids and filetype in files:
                filepath = files[filetype]
                file_id = file_ids[filetype]
                if file_id is not None:
                    files_data.append({"id": file_id, "title": os.path.basename(filepath)})

        complete_data = urllib.parse.urlencode({
            "files": json.dumps(files_data),  # Important: JSON string here
            "channel_id": SLACK_CHANNEL_ID,
            "initial_comment": initial_comment,
        }).encode("utf-8")

        complete_request = urllib.request.Request(
            complete_url, data=complete_data,
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}, method="POST"
        )

        with urllib.request.urlopen(complete_request) as complete_response:
            complete_data = json.loads(complete_response.read().decode("utf-8"))

        if complete_data.get("ok"):
            print("Files uploaded successfully.")
            return complete_data
        else:
            raise Exception(f"Error completing upload: {complete_data}")

    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} {e.reason}")
        send_text_to_slack(f"[{uuid}][ERROR] HTTP Error: {e.code} {e.reason}", SLACK_BOT_TOKEN, SLACK_CHANNEL_ID)
        try:
            error_data = json.loads(e.read().decode('utf-8')) # Try to parse error response
            print(f"Error details: {error_data}")
            send_text_to_slack(f"[{uuid}][ERROR] Details: {error_data}", SLACK_BOT_TOKEN, SLACK_CHANNEL_ID)
        except json.JSONDecodeError:
            send_text_to_slack(f"[{uuid}][ERROR] Details could not be parsed.", SLACK_BOT_TOKEN, SLACK_CHANNEL_ID)
            print("Error details could not be parsed.")
        return None

    except Exception as e:
        import traceback
        stack_trace = traceback.format_exc()  # Capture the stack trace as a string
        print(f"[Send Audio to Slack] Exception occurred: {e}\t{stack_trace}")
        send_text_to_slack(f"[{uuid}][ERROR][ERROR] Exception occurred: {e}\n{stack_trace}", SLACK_BOT_TOKEN, SLACK_CHANNEL_ID)
        return None

# Create Gradio interface with updated theme
with gr.Blocks(
    title="Podcastfy.ai",
    theme=gr.themes.Base(
        primary_hue="blue",
        secondary_hue="slate",
        neutral_hue="slate"
    ),
    css="""
        /* Move toggle arrow to left side */
        .gr-accordion {
            --accordion-arrow-size: 1.5em;
        }
        .gr-accordion > .label-wrap {
            flex-direction: row !important;
            justify-content: flex-start !important;
            gap: 1em;
        }
        .gr-accordion > .label-wrap > .icon {
            order: -1;
        }
    """
) as demo:
    # Add theme toggle at the top
    with gr.Row():
        gr.Markdown("# 🎙️ Podcastfy.ai")
        theme_btn = gr.Button("🌓", scale=0, min_width=0)

    gr.Markdown("An Open Source alternative to NotebookLM's podcast feature")
    gr.Markdown("For full customization, please check Python package on github (www.podcastfy.ai).")

    with gr.Tab("Content"):
        # API Keys Section
        gr.Markdown(
            """
            <h2 style='color: #2196F3; margin-bottom: 10px; padding: 10px 0;'>
                🔑 API Keys
            </h2>
            """,
            elem_classes=["section-header"]
        )
        with gr.Accordion("Configure API Keys", open=False):
            gemini_key = gr.Textbox(
                label="Gemini API Key",
                type="password",
                value=os.getenv("GEMINI_API_KEY", ""),
                info="Required"
            )
            openai_key = gr.Textbox(
                label="OpenAI API Key",
                type="password",
                value=os.getenv("OPENAI_API_KEY", ""),
                info="Required only if using OpenAI TTS model"
            )
            elevenlabs_key = gr.Textbox(
                label="ElevenLabs API Key",
                type="password",
                value=os.getenv("ELEVENLABS_API_KEY", ""),
                info="Required only if using ElevenLabs TTS model [recommended]"
            )

        # Content Input Section
        gr.Markdown(
            """
            <h2 style='color: #2196F3; margin-bottom: 10px; padding: 10px 0;'>
                📝 Input Content
            </h2>
            """,
            elem_classes=["section-header"]
        )
        request_id = gr.Textbox(
            label="Request ID",
            value="",
            info="Unique identifier for the request",
            lines=1
        )
        callback_url = gr.Textbox(
            label="Callback URL",
            value="",
            info="URL to send the generated podcast to",
            lines=1
        )
        with gr.Accordion("Configure Input Content", open=False):
            with gr.Group():
                text_input = gr.Textbox(
                    label="Text Input",
                    placeholder="Enter or paste text here...",
                    lines=3
                )
                urls_input = gr.Textbox(
                    label="URLs",
                    placeholder="Enter URLs (one per line) - supports websites and YouTube videos.",
                    lines=3
                )

                # Place PDF and Image uploads side by side
                with gr.Row():
                    with gr.Column():
                        pdf_files = gr.Files(  # Changed from gr.File to gr.Files
                            label="Upload PDFs",  # Updated label
                            file_types=[".pdf"],
                            type="binary"
                        )
                        gr.Markdown("*Upload one or more PDF files to generate podcast from*", elem_classes=["file-info"])

                    with gr.Column():
                        image_files = gr.Files(
                            label="Upload Images",
                            file_types=["image"],
                            type="binary"
                        )
                        gr.Markdown("*Upload one or more images to generate podcast from*", elem_classes=["file-info"])

        # Customization Section
        gr.Markdown(
            """
            <h2 style='color: #2196F3; margin-bottom: 10px; padding: 10px 0;'>
                ⚙️ Customization Options
            </h2>
            """,
            elem_classes=["section-header"]
        )
        with gr.Accordion("Configure Podcast Settings", open=False):
            # Basic Settings
            gr.Markdown(
                """
                <h3 style='color: #1976D2; margin: 15px 0 10px 0;'>
                    📊 Basic Settings
                </h3>
                """,
            )
            word_count = gr.Slider(
                minimum=500,
                maximum=100000,
                value=2000,
                step=100,
                label="Word Count",
                info="Target word count for the generated content"
            )

            conversation_style = gr.Textbox(
                label="Conversation Style",
                value="engaging,fast-paced,enthusiastic",
                info="Comma-separated list of styles to apply to the conversation"
            )

            # Roles and Structure
            gr.Markdown(
                """
                <h3 style='color: #1976D2; margin: 15px 0 10px 0;'>
                    👥 Roles and Structure
                </h3>
                """,
            )
            roles_person1 = gr.Textbox(
                label="Role of First Speaker",
                value="main summarizer",
                info="Role of the first speaker in the conversation"
            )

            roles_person2 = gr.Textbox(
                label="Role of Second Speaker",
                value="questioner/clarifier",
                info="Role of the second speaker in the conversation"
            )

            dialogue_structure = gr.Textbox(
                label="Dialogue Structure",
                value="Introduction,Main Content Summary,Conclusion",
                info="Comma-separated list of dialogue sections"
            )

            # Podcast Identity
            gr.Markdown(
                """
                <h3 style='color: #1976D2; margin: 15px 0 10px 0;'>
                    🎙️ Podcast Identity
                </h3>
                """,
            )
            podcast_name = gr.Textbox(
                label="Podcast Name",
                value="PODCASTFY",
                info="Name of the podcast"
            )

            podcast_tagline = gr.Textbox(
                label="Podcast Tagline",
                value="YOUR PERSONAL GenAI PODCAST",
                info="Tagline or subtitle for the podcast"
            )

            # Voice Settings
            gr.Markdown(
                """
                <h3 style='color: #1976D2; margin: 15px 0 10px 0;'>
                    🗣️ Voice Settings
                </h3>
                """,
            )
            tts_model = gr.Radio(
                choices=["openai", "elevenlabs", "edge"],
                value="elevenlabs",
                label="Text-to-Speech Model",
                info="Choose the voice generation model (edge is free but of low quality, others are superior but require API keys)"
            )

            # Advanced Settings
            gr.Markdown(
                """
                <h3 style='color: #1976D2; margin: 15px 0 10px 0;'>
                    🔧 Advanced Settings
                </h3>
                """,
            )
            creativity_level = gr.Slider(
                minimum=0,
                maximum=1,
                value=0.7,
                step=0.1,
                label="Creativity Level",
                info="Controls the creativity of the generated conversation (0 for focused/factual, 1 for more creative)"
            )

            user_instructions = gr.Textbox(
                label="Custom Instructions",
                value="",
                lines=2,
                placeholder="Add any specific instructions to guide the conversation...",
                info="Optional instructions to guide the conversation focus and topics"
            )

            voices = gr.Textbox(
                label="Custom Voices",
                value="George, Daniel",
                lines=1,
                placeholder="",
                info="Voices that we should use in the conversation. The first will be the 'Question' voice and the other will be the 'Answer' voice."
            )

            is_mock = gr.Radio(
                choices=["yes", "no", "transcript", "transcript2voice", "PromptOnly"],
                value="yes",
                label="Mock?",
                info="Enable to actually process this request, disable to simulate the process."
            )

            language = gr.Textbox(
                label="Language",
                info="Language of the generated podcast (e.g. Greek, English)",
                value="English",
            )

    # Output Section
    gr.Markdown(
        """
        <h2 style='color: #2196F3; margin-bottom: 10px; padding: 10px 0;'>
            🎵 Generated Output
        </h2>
        """,
        elem_classes=["section-header"]
    )
    with gr.Group():
        generate_btn = gr.Button("🎙️ Generate Podcast", variant="primary")
        audio_output = gr.Audio(
            type="filepath",
            label="Generated Podcast"
        ),
        transcript_output = gr.File(
            type="filepath",
            label="Generated Transcript"
        )

    # Footer
    gr.Markdown("---")
    gr.Markdown("Created with ❤️ using [Podcastfy](https://github.com/souzatharsis/podcastfy)")

    # Handle generation
    generate_btn.click(
        process_inputs,
        inputs=[
            text_input, urls_input, pdf_files, image_files,
            gemini_key, openai_key, elevenlabs_key,
            word_count, conversation_style,
            roles_person1, roles_person2,
            dialogue_structure, podcast_name,
            podcast_tagline, tts_model,
            creativity_level, user_instructions, voices,
            is_mock, request_id, callback_url, language
        ],
        outputs=audio_output
    )

    # Add theme toggle functionality
    theme_btn.click(
        None,
        None,
        None,
        js="""
        function() {
            document.querySelector('body').classList.toggle('dark');
            return [];
        }
        """
    )

if __name__ == "__main__":
    demo.queue().launch(share=True)
