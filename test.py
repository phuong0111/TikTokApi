from TikTokApi import TikTokApi
import asyncio
import os
import json

ms_token = "iJKexdZRwQwvXJGbgSRuJ5nMFtgfV1H-vwG8J8x85AlSBe-d9K4zJEOKSHdsKw5QohPp_9q-UPLKwMs1gZTjlrhkD8zX18eHBOHlJykdeuNDQFqa_a0Qntnpw0QRZ3QEOS5O9cgs7MuRZ3bDgmOHVk4="
results = []

async def user_example():
    async with TikTokApi() as api:
        await api.create_sessions(ms_tokens=[ms_token], num_sessions=1, sleep_after=3, browser=os.getenv("TIKTOK_BROWSER", "chromium"))
        user = api.user("svghongsaigon")
        user_data = await user.info()
        print(user_data)
        
        async for video in user.videos(count=1):
            print(video)
            print(video.as_dict)
            results.append(video.as_dict)
    
    # Move JSON writing inside the async function
    with open("results.json", "w") as fw:
        json.dump(results, fw)

if __name__ == "__main__":
    asyncio.run(user_example())