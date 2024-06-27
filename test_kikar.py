import os
import json
import asyncio
import base64
from typing import Dict, Any
from datetime import datetime
from playwright.async_api import async_playwright
import re

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        try:
            # Example URL (replace with your specific URL)
            article_url = "https://www.kikar.co.il/magazine/sazvzf"

            # Create a new browser context
            context = await browser.new_context()

            # Open a new page within the context
            new_page = await context.new_page()

            # Visit the specified article URL
            await new_page.goto(article_url)

            # Get article information and screenshot
            article_info = await visit_article_and_get_info(new_page)
            if article_info:
                # Create a unique identifier for the article (you can modify this as per your needs)
                original_id = "article_1"
                article_data_with_key: Dict[str, Any] = {original_id: article_info}
                # Save article info to JSON file in test_kikar folder
                output_dir = 'test_kikar'
                output_path = os.path.join(output_dir, f"{original_id}.json")
                save_to_json(article_data_with_key, output_path)
                print(f"Article info saved to {output_path}")

        except Exception as e:
            print(f"Error navigating to article: {e}")

        finally:
            # Close the context and browser
            await context.close()
            await browser.close()

async def get_autor_info(new_page):
    try:
        author_element = await new_page.query_selector('.almoni-tzar.MuiBox-root.css-19f8y51 a')
        author_href = await author_element.get_attribute('href')
        author_text = await author_element.inner_text()

        author = {
            "text": author_text,
            "href": f"https://www.kikar.co.il/{author_href}"
        }
        return author
    except Exception as e:
        print(f"Error getting author information: {e}")
        return None

async def get_time_or_date_published(new_page):
    try:
        # Wait for the parent element to be present
        parent_element = await new_page.wait_for_selector('.almoni-tzar.MuiBox-root.css-19f8y51')

        # Get the inner text of the parent element
        full_text = await parent_element.inner_text()

        # Define regex patterns for time and date
        time_pattern = r'\d{1,2}:\d{2}'  # Matches time in the format 10:30
        date_pattern = r'(\d{1,2}\.\d{2}\.\d{2})'  # Matches date in the format 28.03.24

        # Check if the text contains time or date
        time_match = re.search(time_pattern, full_text)
        date_match = re.search(date_pattern, full_text)

        if time_match:
            # Extract time and combine with today's date
            time_str = time_match.group(0).strip()
            today_date = datetime.now().strftime('%d/%m/%Y')
            return f"{today_date} {time_str}"

        elif date_match:
            # Extract and return the date (only date format)
            date_str = date_match.group(1).strip()
            return date_str
        else:
            print("Neither time nor date found in the text")
            return None
    except Exception as e:
        print(f"Error getting time or date published: {e}")
        return None

async def get_article_content(new_page):
    try:
        # Wait for the article content to load
        await new_page.wait_for_selector('.article-content.MuiBox-root.css-1b737da', timeout=5000)

        # Query the main container element
        main_content_element = await new_page.query_selector('.article-content.MuiBox-root.css-1b737da')

        # Extract all text content under the main container
        content = await main_content_element.inner_text()
        if content:
            content = content.replace("\\", "")
            content = content.replace('\"', "")
            content = content.replace('\n', "")
        return content.strip()  # Strip any leading or trailing whitespace

    except Exception as e:
        print(f"Error getting article content: {e}")
        return None

async def get_images(new_page):
    try:
        image_elements = await new_page.query_selector_all('.MuiBox-root.css-8fjtk0 img')
        images = []

        for element in image_elements:
            image_url = await element.get_attribute('src')
            if image_url:
                # Use Playwright to fetch the image content
                image_response = await new_page.request.get(image_url)
                if image_response.ok:
                    image_data = await image_response.body()
                    image_base64 = base64.b64encode(image_data).decode('utf-8')
                    images.append({
                        'url': image_url,
                        'base64': image_base64
                    })
        return images
    except Exception as e:
        print(f"Error getting images: {e}")
        return []

async def visit_article_and_get_info(new_page):
    article_info = {}
    try:
        # Extract the article details
        headline = await new_page.inner_text('h1')
        author = await get_autor_info(new_page)
        time_published = await get_time_or_date_published(new_page)
        content = await get_article_content(new_page)
        images = await get_images(new_page)

        # Create a dictionary with the extracted details
        article_info = {
            "headline": headline,
            "author": author,
            "time_published": time_published,
            "content": content,
            "images": images
        }

    except Exception as e:
        print(f"Error visiting article: {e}")

    return article_info

def save_to_json(data, output_path):
    # Ensure the test_kikar directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Error saving data to JSON: {e}")

if __name__ == "__main__":
    asyncio.run(main())
