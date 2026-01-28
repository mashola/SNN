import os
import time
import asyncio
import requests
import feedparser
import subprocess
import edge_tts
from deep_translator import GoogleTranslator

# Configuration - Stream to YouTube RTMP servers
YOUTUBE_URL = "rtmp://a.rtmp.youtube.com/live2/"
STREAM_KEY = os.getenv("YOUTUBE_STREAM_KEY")

RSS_FEEDS = [
    "https://www.bbc.com/swahili/index.xml",
    "https://www.dw.com/sw/habari/rss-30740-swahili"
]

def get_news():
    """Scrapes RSS feeds for the latest news stories and images."""
    print("\n--- [1/4] Fetching Latest News ---")
    articles = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:6]: 
                img_url = None
                if 'media_content' in entry:
                    img_url = entry.media_content[0]['url']
                elif 'links' in entry:
                    for link in entry.links:
                        if 'image' in link.get('type', ''):
                            img_url = link.get('href')
                
                if not img_url:
                    img_url = f"https://picsum.photos/1920/1080?random={time.time()}"

                articles.append({
                    "title": entry.title or "Habari Mpya",
                    "summary": entry.summary or entry.title or "Maelezo hayapatikani kwa sasa.",
                    "image": img_url
                })
        except Exception as e:
            print(f"Feed error: {e}")
    return articles

async def generate_audio_with_retry(text, voice, outfile, retries=3):
    """Generates audio with a retry mechanism for robustness."""
    for i in range(retries):
        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(outfile)
            if os.path.exists(outfile) and os.path.getsize(outfile) > 0:
                return True
        except Exception as e:
            print(f"TTS Attempt {i+1} failed: {e}")
            await asyncio.sleep(2)
    return False

async def generate_assets(news_item, index):
    """Translates content, generates neural voice, and renders 1080p video."""
    try:
        # 1. Translation
        print(f"Segment {index}: Translating...")
        translator = GoogleTranslator(source='auto', target='sw')
        translated = translator.translate(news_item['summary'])
        
        if not translated or len(translated.strip()) < 5:
            translated = news_item['title'] # Fallback to title if summary fails

        script = " ".join(translated.split()[:80]) + "."

        # 2. High Quality Microsoft Neural TTS
        print(f"Segment {index}: Generating Audio...")
        # primary voice: sw-TZ-LughaNeural, fallback: sw-KE-ZuriNeural
        audio_file = f"audio_{index}.mp3"
        success = await generate_audio_with_retry(script, "sw-TZ-LughaNeural", audio_file)
        
        if not success:
            print(f"Segment {index}: Trying fallback voice...")
            success = await generate_audio_with_retry(script, "sw-KE-ZuriNeural", audio_file)

        if not success:
            raise Exception("Failed to generate audio after multiple attempts.")

        # 3. Download Image
        img_file = f"image_{index}.jpg"
        img_res = requests.get(news_item['image'], timeout=15)
        with open(img_file, 'wb') as f:
            f.write(img_res.content)

        # 4. Rendering Video
        output_video = f"segment_{index}.mp4"
        print(f"Segment {index}: Rendering Video...")
        
        duration_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_file]
        duration = subprocess.check_output(duration_cmd).decode('utf-8').strip()

        ffmpeg_cmd = [
            'ffmpeg', '-y', '-loop', '1', '-i', img_file, '-i', audio_file,
            '-t', duration, '-pix_fmt', 'yuv420p',
            '-vf', "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,boxblur=20:5 [bg]; [0:v] scale=1920:1080:force_original_aspect_ratio=decrease [fg]; [bg][fg] overlay=(W-w)/2:(H-h)/2",
            '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', '-b:a', '128k', '-shortest', output_video
        ]
        subprocess.run(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        return output_video
    except Exception as e:
        print(f"Error in segment {index}: {e}")
        return None

async def broadcast_loop():
    if not STREAM_KEY:
        print("CRITICAL: YOUTUBE_STREAM_KEY secret is missing!")
        return

    while True:
        items = get_news()
        video_segments = []
        
        for i, item in enumerate(items):
            video = await generate_assets(item, i)
            if video:
                video_segments.append(video)
                await asyncio.sleep(1) # Small delay to prevent rate limiting
        
        if not video_segments:
            print("No segments generated. Waiting 60s...")
            await asyncio.sleep(60)
            continue

        with open("playlist.txt", "w") as f:
            for v in video_segments:
                f.write(f"file '{v}'\n")

        print("--- [STREAMING] Pushing to YouTube ---")
        stream_cmd = [
            'ffmpeg', '-re', '-f', 'concat', '-safe', '0', '-i', 'playlist.txt',
            '-vcodec', 'libx264', '-preset', 'veryfast', '-maxrate', '4500k', 
            '-bufsize', '9000k', '-pix_fmt', 'yuv420p', '-g', '60', 
            '-c:a', 'aac', '-b:a', '128k', '-ar', '44100',
            '-f', 'flv', f"{YOUTUBE_URL}{STREAM_KEY}"
        ]
        subprocess.run(stream_cmd)
        
        for f in os.listdir():
            if f.endswith((".mp4", ".mp3", ".jpg")):
                try: os.remove(f)
                except: pass

if __name__ == "__main__":
    asyncio.run(broadcast_loop())
