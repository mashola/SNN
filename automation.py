import os
import time
import asyncio
import requests
import feedparser
import subprocess
import edge_tts
from deep_translator import GoogleTranslator

# Configuration - YouTube RTMP Stream
YOUTUBE_URL = "rtmp://a.rtmp.youtube.com/live2/"
# Set this secret in your GitHub Repository Settings
STREAM_KEY = os.getenv("YOUTUBE_STREAM_KEY")

RSS_FEEDS = [
    "https://www.bbc.com/swahili/index.xml",
    "https://www.dw.com/sw/habari/rss-30740-swahili"
]

def get_news():
    """Fetches the latest news and images from RSS feeds."""
    print("\n--- [1/4] Fetching Fresh News ---")
    articles = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:6]:
                img_url = None
                # Extract image URL from entry
                if 'media_content' in entry:
                    img_url = entry.media_content[0]['url']
                elif 'links' in entry:
                    for link in entry.links:
                        if 'image' in link.get('type', ''):
                            img_url = link.get('href')
                
                if not img_url:
                    img_url = f"https://picsum.photos/1920/1080?random={time.time()}"

                articles.append({
                    "title": entry.title,
                    "summary": entry.summary,
                    "image": img_url
                })
        except Exception as e:
            print(f"Feed error: {e}")
    return articles

async def generate_assets(news_item, index):
    """Translates content, generates high-quality neural voiceover, and renders video."""
    try:
        # 1. Translation
        print(f"Segment {index}: Translating...")
        translated = GoogleTranslator(source='auto', target='sw').translate(news_item['summary'])
        script = " ".join(translated.split()[:75]) + "."

        # 2. Neural TTS (High Quality Microsoft Voice - FREE)
        print(f"Segment {index}: Generating Neural Audio...")
        voice = "sw-TZ-LughaNeural" # Professional Tanzanian Swahili
        audio_file = f"audio_{index}.mp3"
        communicate = edge_tts.Communicate(script, voice)
        await communicate.save(audio_file)

        # 3. Image Download
        img_file = f"image_{index}.jpg"
        img_res = requests.get(news_item['image'], timeout=15)
        with open(img_file, 'wb') as f:
            f.write(img_res.content)

        # 4. Professional 1080p Video Rendering
        output_video = f"segment_{index}.mp4"
        print(f"Segment {index}: Rendering Cinematic Video...")
        
        # Get audio duration
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

async def main_loop():
    if not STREAM_KEY:
        print("CRITICAL: YOUTUBE_STREAM_KEY secret is not set in GitHub Settings.")
        return

    while True:
        items = get_news()
        video_segments = []
        
        for i, item in enumerate(items):
            video = await generate_assets(item, i)
            if video: video_segments.append(video)
        
        if not video_segments:
            await asyncio.sleep(60)
            continue

        with open("playlist.txt", "w") as f:
            for v in video_segments:
                f.write(f"file '{v}'\n")

        print("--- Pushing Stream to YouTube ---")
        stream_cmd = [
            'ffmpeg', '-re', '-f', 'concat', '-safe', '0', '-i', 'playlist.txt',
            '-vcodec', 'libx264', '-preset', 'veryfast', '-maxrate', '4500k', 
            '-bufsize', '9000k', '-pix_fmt', 'yuv420p', '-g', '60', 
            '-c:a', 'aac', '-b:a', '128k', '-ar', '44100',
            '-f', 'flv', f"{YOUTUBE_URL}{STREAM_KEY}"
        ]
        subprocess.run(stream_cmd)
        
        # Cleanup
        for f in os.listdir():
            if f.endswith((".mp4", ".mp3", ".jpg")):
                try: os.remove(f)
                except: pass

if __name__ == "__main__":
    asyncio.run(main_loop())
