from copy import deepcopy
from dotenv import load_dotenv
import requests
import base64
import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, ContextTypes, MessageHandler, filters


load_dotenv()


webui_server_url = os.getenv('SERVER_URL', 'http://127.0.0.1:7860/')
tg_token = os.getenv('TG_TOKEN', None)
model = os.getenv('MODEL', None)
sampler = os.getenv('SAMPLER', 'DPM++ 2M')
scheduler = os.getenv('SCHEDULER', 'Karras')
cfg_scale = int(os.getenv('CFG_SCALE', 7))
denoising_strength = float(os.getenv('DENOISING_STRENGTH', 0.75))
steps = int(os.getenv('STEPS', 25))
clip_stop_at = int(os.getenv('CLIP_LAYERS', 2))
seed = int(os.getenv('SEED', -1))
width = int(os.getenv('WIDTH', 512))
height = int(os.getenv('HEIGHT', 512))
restore_faces = os.getenv('RESTORE_FACES', 'True').lower() in ('true')
negative_prompt = os.getenv('NEGATIVE_PROMPT', '')
resize_mode = int(os.getenv('RESIZE_MODE', 0))
loras = os.getenv('LORAS', '')
img2img_controlnet = os.getenv('CONTROLNET_ENABLE', 'False').lower() in ('true')
controlnet_module = os.getenv('CONTROLNET_MODULE', 'none')
controlnet_mode = int(os.getenv('CONTROLNET_MODE', 0))
recursive_upscale = os.getenv('RECURSIVE_UPSCALE', 'False').lower() in ('true')
controlnet_upscale_model = os.getenv('CONTROLNET_UPSCALE_MODEL', 'none')


base_payload = {
    "steps":steps,
    "negative_prompt":negative_prompt,
    "override_settings": {
        'sd_model_checkpoint': model,
        "CLIP_stop_at_last_layers": clip_stop_at,
    },
    "override_settings_restore_afterwards": True,
    "sampler_name":sampler,
    "scheduler":scheduler,
    "cfg_scale": cfg_scale,
    "seed": seed,
    "width":width,
    "height":height,
    "restore_faces":restore_faces,
    "denoising_strength": denoising_strength,
}


def control_net(init_photo):
    return {
                "controlnet": {
                    "args": [
                        {
                            "input_image": encode_to_base64(init_photo),
                            "module": controlnet_module,
                            "control_mode": controlnet_mode,
                            "processor_res": 512,
                            "threshold_a": 0.5,
                            "threshold_b": 0.5,
                        }
                    ]
                }
            }


def get_markup(option_choice=''):
    if 'Upscaled' not in option_choice:
        keyboard = [[InlineKeyboardButton("Try again", callback_data="TRYAGAIN"), InlineKeyboardButton("Variation", callback_data="VARIATION"), InlineKeyboardButton("Upscale", callback_data="UPSCALE")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        return reply_markup
    else:
        keyboard = [[InlineKeyboardButton("Try again", callback_data="TRYAGAIN"), InlineKeyboardButton("Variation", callback_data="VARIATION")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        return reply_markup


def encode_to_base64(image_bytes):
    return base64.b64encode(image_bytes).decode('utf-8')


def decode_from_base64(base64_str):
    return base64.b64decode(base64_str)


async def call_api(api_endpoint, **payload):
    data = json.dumps(payload).encode('utf-8')
    url = '{a}{b}'.format(a=webui_server_url, b=api_endpoint)
    try:
        response = requests.post(
            url,
            headers={'Content-Type': 'application/json'},
            data=data,
        )
        jsonResponse = response.json()
        generation_time = response.elapsed.total_seconds()
        try:
            info = eval(jsonResponse['info'].replace("true","True").replace("false","False").replace("null", "0"))
            imgseed = int(info['seed'])
            return decode_from_base64(jsonResponse['images'][0]), imgseed, generation_time
        except Exception:
            error_details = jsonResponse['detail']
            print(jsonResponse)
            return error_details, None, None
    except requests.exceptions.RequestException as e:
        print(e)
        return None, None, None


async def upscale(upscale_endpoint, upscale_photo, upscale_prompt, upscale_denoising_strength=0.3):
    upscale_payload = deepcopy(base_payload)
    upscale_payload['prompt'] = upscale_prompt
    upscale_payload['steps'] = 50
    upscale_payload['cfg_scale'] = 6
    upscale_payload['init_images'] = [encode_to_base64(upscale_photo),]
    upscale_payload['denoising_strength'] = upscale_denoising_strength
    upscale_payload['alwayson_scripts'] = {
                        "controlnet": {
                            "args": [
                                {
                                    "input_image": encode_to_base64(upscale_photo),
                                    "module": "tile_resample",
                                    "model": controlnet_upscale_model,
                                    "control_mode": 2,
                                    "processor_res": 512,
                                    "threshold_a": 1.0,
                                    "threshold_b": 0.5,
                                }
                            ]
                        }
                    }
    upscale_payload['script_name'] = "Ultimate SD upscale"
    upscale_payload['script_args'] = [
                None,
                512,
                0,
                8,
                32,
                64,
                0.35,
                16,
                4,
                True,
                0,
                False,
                4,
                0,
                2,
                2048,
                2048,
                2
            ]
    
    if recursive_upscale and upscale_denoising_strength > 0.2:
        upscale_image_pass_one, upscale_seed_pass_one, upscale_generation_time = await call_api(upscale_endpoint, **upscale_payload)
        return await upscale(upscale_endpoint, upscale_image_pass_one, upscale_prompt, 0.15)
    else:
        return await call_api(upscale_endpoint, **upscale_payload)


async def send_message(update: Update, context: ContextTypes.DEFAULT_TYPE, image, delete_chat_id, delete_message_id, send_chat_id, reply_message_id, prompt, image_seed, image_generation_time, option_button_choice='New') -> None:
    if isinstance(image, (bytes, bytearray)):
        await context.bot.delete_message(chat_id=delete_chat_id, message_id=delete_message_id)
        formatted_seed = str(image_seed)
        formatted_time = round(image_generation_time, 1)
        await context.bot.send_photo(send_chat_id, image, caption=f'"{prompt}" ({option_button_choice}) \n\nSeed: {formatted_seed}\nSteps: {steps}\nTime: {formatted_time}s', reply_markup=get_markup(option_button_choice), reply_to_message_id=reply_message_id)
    elif image is None:
        await context.bot.delete_message(chat_id=delete_chat_id, message_id=delete_message_id)
        await context.bot.send_message(send_chat_id, 'I can\'t reach Stable diffusion right now, come back later \U0001F607')
    else:
        await context.bot.delete_message(chat_id=delete_chat_id, message_id=delete_message_id)
        await context.bot.send_message(send_chat_id, f'Stable Diffusion hit a snag \U0001F62D Here is the error: {image}')


async def nesting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    original_raw = update.message.reply_to_message.text if update.message.reply_to_message.text is not None else update.message.reply_to_message.caption
    if not original_raw.startswith("!dream"):
        return
    nesting_msg = await update.message.reply_text("Dreaming...", reply_to_message_id=update.message.message_id)
    original_prompt = original_raw.replace("!dream","").strip() if original_raw.startswith("!dream") else original_raw.split('"')[1::2][0]
    nesting_prompt = (original_prompt+", "+update.message.text).replace(",,", ",").replace("\"","\'").strip()
    if update.message.reply_to_message.photo:
        nesting_img2img_photo_file = await update.message.reply_to_message.photo[-1].get_file()
        nesting_img2img_photo = await nesting_img2img_photo_file.download_as_bytearray()
        nesting_img2img_payload = deepcopy(base_payload)
        nesting_img2img_payload['prompt'] = (nesting_prompt+", "+loras).replace(",,", ",")
        nesting_img2img_payload['init_images'] = [encode_to_base64(nesting_img2img_photo),]
        if img2img_controlnet:
            nesting_img2img_payload['alwayson_scripts'] = control_net(nesting_img2img_photo)
        nesting_img2img_endpoint = 'sdapi/v1/img2img'
        nesting_image, nesting_seed, nesting_generation_time = await call_api(nesting_img2img_endpoint,**nesting_img2img_payload)
    else:
        nesting_txt2img_payload = deepcopy(base_payload)
        nesting_txt2img_payload['prompt'] = (nesting_prompt+", "+loras).replace(",,", ",")
        nesting_txt2img_endpoint = 'sdapi/v1/txt2img'
        nesting_image, nesting_seed, nesting_generation_time = await call_api(nesting_txt2img_endpoint, **nesting_txt2img_payload)
    
    await send_message(update, context, nesting_image, nesting_msg.chat_id, nesting_msg.message_id, update.message.chat_id, update.message.message_id, nesting_prompt, nesting_seed, nesting_generation_time)
    

async def txt2img(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message.text.startswith("!dream") or len(update.message.text.split()) < 2:
        return
    txt2img_msg = await update.message.reply_text("Dreaming...", reply_to_message_id=update.message.message_id)
    txt2img_prompt = update.message.text.replace("!dream","").replace("\"","\'").strip()
    txt2img_payload = {}
    txt2img_payload = deepcopy(base_payload)
    txt2img_payload['prompt'] = (txt2img_prompt+", "+loras).replace(",,", ",")
    txt2img_endpoint = 'sdapi/v1/txt2img'
    txt2img_image, txt2img_seed, txt2img_generation_time = await call_api(txt2img_endpoint, **txt2img_payload)

    await send_message(update, context, txt2img_image, txt2img_msg.chat_id, txt2img_msg.message_id, update.message.chat_id, update.message.message_id, txt2img_prompt, txt2img_seed, txt2img_generation_time)


async def img2img(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.caption is None:
        await update.message.reply_text("The photo must have a caption that contains a prompt starting with '!dream'", reply_to_message_id=update.message.message_id)
        return
    if not update.message.caption.startswith("!dream") or len(update.message.caption.split()) < 2:
        return
    img2img_msg = await update.message.reply_text("Dreaming...", reply_to_message_id=update.message.message_id)
    img2img_photo_file = await update.message.photo[-1].get_file()
    img2img_photo = await img2img_photo_file.download_as_bytearray()
    img2img_payload = deepcopy(base_payload)
    img2img_prompt = update.message.caption.replace("!dream","").replace("\"","\'").strip()
    img2img_payload['prompt'] = (img2img_prompt+", "+loras).replace(",,", ",")
    img2img_payload['init_images'] = [encode_to_base64(img2img_photo),]
    img2img_payload['resize_mode'] = resize_mode
    if img2img_controlnet:
        img2img_payload['alwayson_scripts'] = control_net(img2img_photo)
    img2img_endpoint = 'sdapi/v1/img2img'
    img2img_image, img2img_seed, img2img_generation_time = await call_api(img2img_endpoint,**img2img_payload)

    await send_message(update, context, img2img_image, img2img_msg.chat_id, img2img_msg.message_id, update.message.chat_id, update.message.message_id, img2img_prompt, img2img_seed, img2img_generation_time)


async def options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    original_message = query.message.reply_to_message

    await query.answer()

    option_prompt = query.message.caption.split('\"')[1::2][0]

    if query.data == "TRYAGAIN":
        option_msg = await query.message.reply_text("Dreaming again...", reply_to_message_id=original_message.message_id)
        option_type = 'Retry'
        if original_message.photo:
            tryagain_img2img_photo_file = await original_message.photo[-1].get_file()
            tryagain_img2img_photo = await tryagain_img2img_photo_file.download_as_bytearray()
            tryagain_img2img_payload = deepcopy(base_payload)
            tryagain_img2img_payload['prompt'] = (option_prompt+", "+loras).replace(",,", ",")
            tryagain_img2img_payload['init_images'] = [encode_to_base64(tryagain_img2img_photo),]
            tryagain_img2img_payload['resize_mode'] = resize_mode
            if img2img_controlnet:
                tryagain_img2img_payload['alwayson_scripts'] = control_net(tryagain_img2img_photo)
            tryagain_img2img_endpoint = 'sdapi/v1/img2img'
            option_image, option_seed, option_generation_time = await call_api(tryagain_img2img_endpoint,**tryagain_img2img_payload)
        else:
            tryagain_txt2img_payload = deepcopy(base_payload)
            tryagain_txt2img_payload['prompt'] = (option_prompt+", "+loras).replace(",,", ",")
            tryagain_txt2img_endpoint = 'sdapi/v1/txt2img'
            option_image, option_seed, option_generation_time = await call_api(tryagain_txt2img_endpoint, **tryagain_txt2img_payload)

    elif query.data == "VARIATION":
        option_msg = await query.message.reply_text("Generating dream variation...", reply_to_message_id=query.message.message_id)
        variation_img2img_photo_file = await query.message.photo[-1].get_file()
        variation_img2img_photo = await variation_img2img_photo_file.download_as_bytearray()
        variation_img2img_endpoint = 'sdapi/v1/img2img'
        variation_img2img_payload = deepcopy(base_payload)
        variation_img2img_payload['prompt'] = (option_prompt+", "+loras).replace(",,", ",")
        variation_img2img_payload['init_images'] = [encode_to_base64(variation_img2img_photo),]
        variation_img2img_payload['resize_mode'] = resize_mode
        option_image, option_seed, option_generation_time = await call_api(variation_img2img_endpoint,**variation_img2img_payload)
        option_type = 'Variation'

    elif query.data == "UPSCALE":
        option_msg = await query.message.reply_text("Upscaling dream...", reply_to_message_id=query.message.message_id)
        upscale_img2img_photo_file = await query.message.photo[-1].get_file()
        upscale_img2img_photo = await upscale_img2img_photo_file.download_as_bytearray()
        upscale_img2img_endpoint = 'sdapi/v1/img2img'
        upscale_img2img_prompt = (option_prompt+", "+loras).replace(",,", ",")
        option_image, option_seed, option_generation_time = await upscale(upscale_img2img_endpoint, upscale_img2img_photo, upscale_img2img_prompt)
        option_type = 'Upscaled'

    await send_message(update, context, option_image, option_msg.chat_id, option_msg.message_id, query.message.chat_id, query.message.message_id, option_prompt, option_seed, option_generation_time, option_type)


if __name__ == '__main__':
    try:
        app = ApplicationBuilder().token(tg_token).build()

        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.REPLY, txt2img))
        app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND & ~filters.REPLY, img2img))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.REPLY, nesting))
        
        app.add_handler(CallbackQueryHandler(options))

        app.run_polling()
    except Exception as e:
        print(e)