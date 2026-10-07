import sys
import os
import requests
import argparse
from fast_mail_parser import parse_email
import pdb

def email_analysis(email):
    return


def unsubscribe_request(url):
    user_agent = f"NortheasternISecLabUnsubscribeStudy/1.0 (+https://exampleStudyDomain.tld; abuse@sub.exampleStudyDomain.tld)" #TODO: fill with real values instead of placeholders
    request = requests.post(
        url=url,
        headers={"User-Agent":user_agent,"Content-Type":"application/x-www-form-urlencoded"},
        data=b"List-Unsubscribe=One-Click",
        verify=False,
        allow_redirects=False,
        timeout=30,
        proxies={"http":"http://127.0.0.1:8080", "https":"http://127.0.0.1:8080"} #TODO: Remove proxies => these are for local testing / Can just comment out
    )
    return request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("src", help="The source directory containing .eml files which will be parsed.")

    args = parser.parse_args()

    if not args.src:
        sys.exit(-1)

    src = args.src

    files = os.listdir(src)
    files = [os.path.join(src,f) for f in files if f.endswith(".eml") and os.path.isfile(os.path.join(src, f))]

    for file in files:
        with open(file, 'rb') as f:
            email = parse_email(f.read())
            header_list = email.headers.keys()
            unsubscribe_url = ""
            addr = ""
            if not 'List-Unsubscribe' in header_list:
                print("[-] No Unsubscribe header!")
                continue
            else:
                if 'List-Unsubscribe' in header_list and not 'List-Unsubscribe-Post' in header_list:
                    print("[!] Not a true OneClick process!")
                else:
                    print("[+] True OneClick!")
                    # reply_to = email.headers['Reply-To']
                    for option in email.headers['List-Unsubscribe']:
                        value = option[1:-1]
                        if value.startswith(("http://", "https://")):
                            unsubscribe_url = value
            addr = email.headers['To'][0]
            print("==================")
            print(f"Email alias: {addr}")
            print(f"Unsubscribe link: {unsubscribe_url}")
            print(f"Authentication result: {email.headers['Authentication-Results']}")
            unsubscribe_request(unsubscribe_url+"5512341234")
            # pdb.set_trace()
            print("==================")






if __name__ == "__main__":
    main()