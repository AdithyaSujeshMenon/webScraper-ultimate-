import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urldefrag
import zipfile
import logging
from tqdm import tqdm
import concurrent.futures
import re
import magic
import json
import time
import hashlib
import base64
import js2py
import cssutils
import xml.etree.ElementTree as ET
from collections import deque
from io import BytesIO


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
cssutils.log.setLevel(logging.CRITICAL)


def generate_filename(url, content):
    hash_object = hashlib.sha256(content)
    file_hash = hash_object.hexdigest()
    return f"{file_hash}_{os.path.basename(urlparse(url).path) or 'index.html'}"


def fetch_url(url, session):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = session.get(url, timeout=30, headers=headers, stream=True)
        response.raise_for_status()
        return response
    except requests.RequestException as e:
        logging.error(f"Failed to fetch {url}: {e}")
        return None


def extract_urls_from_css(css_content, base_url):
    urls = set()
    try:
        sheet = cssutils.parseString(css_content)
        for rule in sheet:
            if rule.type == rule.STYLE_RULE:
                for property in rule.style:
                    if property.name in ['background-image', 'background', 'content']:
                        urls.update(re.findall(r'url\([\'"]?([^\'"()]+)[\'"]?\)', property.value))
    except Exception as e:
        logging.warning(f"Failed to parse CSS from {base_url}: {e}")
    return [urljoin(base_url, url) for url in urls]


def extract_urls_from_js(js_content, base_url):
    urls = set()
    try:
        context = js2py.EvalJs()
        context.execute(js_content)
        urls.update(re.findall(r'(?:url\(|[\'"])\s*([^\'"()]+)\s*(?:\)|[\'"])', js_content))
        # Add more specific parsing logic as needed for JS files
    except Exception as e:
        logging.warning(f"Failed to parse JavaScript from {base_url}: {e}")
    return [urljoin(base_url, url) for url in urls]


def extract_urls_from_xml(xml_content, base_url):
    urls = set()
    try:
        root = ET.fromstring(xml_content)
        for elem in root.iter():
            if 'href' in elem.attrib:
                urls.add(elem.attrib['href'])
            if 'src' in elem.attrib:
                urls.add(elem.attrib['src'])
    except Exception as e:
        logging.warning(f"Failed to parse XML from {base_url}: {e}")
    return [urljoin(base_url, url) for url in urls]


def parse_content(content, base_url, content_type):
    urls = set()
    soup = None

    if 'html' in content_type:
        soup = BeautifulSoup(content, 'html.parser')
        for tag in soup.find_all(True):
            for attr in ['src', 'href', 'data', 'poster']:
                if tag.has_attr(attr):
                    urls.add(urljoin(base_url, tag[attr]))
        for style in soup.find_all('style'):
            urls.update(extract_urls_from_css(style.string, base_url))
        for script in soup.find_all('script'):
            if script.string:
                urls.update(extract_urls_from_js(script.string, base_url))
    elif 'css' in content_type:
        urls.update(extract_urls_from_css(content, base_url))
    elif 'javascript' in content_type:
        urls.update(extract_urls_from_js(content, base_url))
    elif 'xml' in content_type:
        urls.update(extract_urls_from_xml(content, base_url))

    urls.update(re.findall(r'(?:url\(|[\'"])\s*([^\'"()]+)\s*(?:\)|[\'"])', content))

    return list(urls), soup


def download_file(url, session):
    try:
        response = fetch_url(url, session)
        if not response:
            return None

        content = response.content
        content_type = response.headers.get('Content-Type', '').split(';')[0]
        file_name = generate_filename(url, content)
        return file_name, content, content_type
    except Exception as e:
        logging.error(f"Failed to download {url}: {e}")
        return None


def create_zip(download_folder, output_zip):
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(download_folder):
            for file in files:
                file_path = os.path.join(root, file)
                zipf.write(file_path, os.path.relpath(file_path, download_folder))


def update_html_references(soup, file_mapping):
    for tag in soup.find_all(True):
        for attr in ['src', 'href', 'data', 'poster']:
            if tag.has_attr(attr):
                old_url = tag[attr]
                new_url = file_mapping.get(urldefrag(urljoin(soup.base['href'], old_url))[0])
                if new_url:
                    tag[attr] = os.path.relpath(new_url, os.path.dirname(soup.base['href']))
    return str(soup)

#Made By Adithya Sujesh Menon(GitHub:unknown7-O)

def scrape_website(url, output_zip, max_depth=float('inf'), max_files=float('inf'), delay=0):
    download_folder = 'downloaded_website'
    if os.path.exists(download_folder):
        for root, _, files in os.walk(download_folder, topdown=False):
            for file in files:
                os.remove(os.path.join(root, file))
            os.rmdir(root)

    os.makedirs(download_folder, exist_ok=True)

    visited_urls = set()
    file_mapping = {}
    to_visit = deque([(url, 0)])  # (url, depth)
    file_count = 0

    with requests.Session() as session:
        with tqdm(total=max_files, desc="Downloading files") as pbar:
            while to_visit and file_count < max_files:
                current_url, current_depth = to_visit.popleft()

                if current_url in visited_urls or current_depth > max_depth:
                    continue

                visited_urls.add(current_url)

                time.sleep(delay)

                response = fetch_url(current_url, session)
                if not response:
                    continue

                content = response.content
                content_type = response.headers.get('Content-Type', '').split(';')[0]

                urls, soup = parse_content(content.decode('utf-8', 'ignore'), current_url, content_type)

                result = download_file(current_url, session)
                if result:
                    file_name, file_content, content_type = result
                    file_path = os.path.join(download_folder, file_name)
                    with open(file_path, 'wb') as file:
                        file.write(file_content)
                    file_mapping[current_url] = file_path
                    file_count += 1
                    pbar.update(1)

                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    future_to_url = {executor.submit(download_file, url, session): url for url in urls if url not in visited_urls and file_count < max_files}

                    for future in concurrent.futures.as_completed(future_to_url):
                        url = future_to_url[future]
                        result = future.result()
                        if result:
                            file_name, file_content, content_type = result
                            file_path = os.path.join(download_folder, file_name)
                            with open(file_path, 'wb') as file:
                                file.write(file_content)
                            file_mapping[url] = file_path
                            file_count += 1
                            pbar.update(1)

                            if urlparse(url).netloc == urlparse(current_url).netloc:
                                to_visit.append((url, current_depth + 1))

                if soup and 'html' in content_type:
                    soup.base = None
                    soup.base = soup.new_tag('base', href=current_url)
                    soup.head.insert(0, soup.base)
                    updated_html = update_html_references(soup, file_mapping)
                    with open(file_path, 'w', encoding='utf-8') as file:
                        file.write(updated_html)

    create_zip(download_folder, output_zip)
    logging.info(f"Website files have been successfully zipped into {output_zip}")

    metadata = {
        'total_files': file_count,
        'visited_urls': list(visited_urls),
        'file_mapping': {k: os.path.relpath(v, download_folder) for k, v in file_mapping.items()}
    }
    with open(os.path.join(download_folder, 'metadata.json'), 'w') as f:
        json.dump(metadata, f, indent=2)

    for root, _, files in os.walk(download_folder, topdown=False):
        for file in files:
            os.remove(os.path.join(root, file))
        os.rmdir(root)


def main_menu():
    url = ""
    output_zip = "website_content.zip"
    max_depth = float('inf')
    max_files = float('inf')
    delay = 0

    while True:
        print("\n--- Ultimate Website Scraper ---")
        print("1. Set URL")
        print("2. Set output ZIP file name")
        print("3. Set maximum depth")
        print("4. Set maximum number of files")
        print("5. Set delay between requests (seconds)")
        print("6. Start scraping")
        print("7. Exit")

        choice = input("Enter your choice (1-7): ")

        if choice == '1':
            url = input("Enter the URL to scrape: ")
        elif choice == '2':
            output_zip = input("Enter the output ZIP file name: ")
        elif choice == '3':
            try:
                max_depth = int(input("Enter the maximum depth (0 for unlimited): "))
                if max_depth == 0:
                    max_depth = float('inf')
            except ValueError:
                print("Invalid input. Please enter a number.")
        elif choice == '4':
            try:
                max_files = int(input("Enter the maximum number of files (0 for unlimited): "))
                if max_files == 0:
                    max_files = float('inf')
            except ValueError:
                print("Invalid input. Please enter a number.")
        elif choice == '5':
            try:
                delay = float(input("Enter the delay between requests in seconds: "))
                if delay < 0:
                    print("Delay cannot be negative. Setting delay to 0 seconds.")
                    delay = 0
            except ValueError:
                print("Invalid input. Please enter a number.")
        elif choice == '6':
            if not url:
                print("Please set a URL first.")
            else:
                print(f"\nStarting to scrape {url}")
                print(f"Output will be saved to {output_zip}")
                print(f"Maximum depth: {'Unlimited' if max_depth == float('inf') else max_depth}")
                print(f"Maximum files: {'Unlimited' if max_files == float('inf') else max_files}")
                print(f"Delay between requests: {delay} seconds")
                confirm = input("Do you want to proceed? (y/n): ")
                if confirm.lower() == 'y':
                    scrape_website(url, output_zip, max_depth, max_files, delay)
                else:
                    print("Scraping cancelled.")
        elif choice == '7':
            print("Exiting the program. Goodbye!")
            break
        else:
            print("Invalid choice. Please enter a number between 1 and 7.")

if __name__ == "__main__":
    main_menu()
