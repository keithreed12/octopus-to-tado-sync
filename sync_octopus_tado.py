import argparse
import asyncio
import requests
from datetime import datetime, timedelta
from requests.auth import HTTPBasicAuth
from playwright.async_api import async_playwright
from PyTado.interface import Tado
import json
from URLDecoder.decoder import URLDecoder

TOKEN_FILE_PATH="/tmp/tado_refresh_token"

header = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer xx'}

def get_meter_reading_total_consumption(api_key, mprn, gas_serial_number, tado_token):
    header['Authorization'] = f'Bearer {tado_token}'
    
    resp=requests.get('https://energy-insights.tado.com/api/homes/1898784/heatingBills', headers=header)
    latest = resp.json()['heatingBills'][0]['endDate']
    yesterday = (datetime.now() - timedelta(1)).strftime('%Y-%m-%d')
    print(f"Latest reading: {latest}, yesterday's date: {yesterday}")
    total_consumption = 0.0

    if latest >= yesterday:
        print(f"Already sent reading for today {yesterday}")
    else:
        period_from = datetime.fromisoformat(latest)
        url = f"https://api.octopus.energy/v1/gas-meter-points/{mprn}/meters/{gas_serial_number}/consumption/?group_by=day&period_from={period_from.isoformat()}Z"

        while url:
            response = requests.get(url, auth=HTTPBasicAuth(api_key, ""))

            if response.status_code == 200:
                meter_readings = response.json()
                print(meter_readings)
                total_consumption += sum(
                    interval["consumption"] for interval in meter_readings["results"]
                )
                for interval in meter_readings["results"]:
                    bill = {
                        'startDate': interval["interval_start"][0:10],
                        'endDate': interval["interval_end"][0:10],
                        'consumption': interval["consumption"],
                        'unitPriceInCents': 674
                    }
                    if (bill['startDate'] != bill['endDate']):
                        resp=requests.post('https://energy-insights.tado.com/api/homes/1898784/heatingBills',
                                        data=json.dumps(bill), headers=header)
#                    print(bill)
#                    print (resp.text)
                    
                url = meter_readings.get("next", "")
            else:
                print(
                    f"Failed to retrieve data. Status code: {response.status_code}, Message: {response.text}"
                )
                break

        print(f"Total consumption is {total_consumption}")
    return total_consumption


async def browser_login(url, username, password):

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True
        )  # Set to True if you don't want a browser window
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(url)

        # Click the "Submit" button before login
        await page.wait_for_selector('text="Submit"', timeout=5000)
        await page.click('text="Submit"')

        # Wait for the login form to appear
        await page.wait_for_selector('input[name="loginId"]')

        # Replace with actual selectors for your site
        await page.fill('input[id="loginId"]', username)
        await page.fill('input[name="password"]', password)

        await page.click('button.c-btn--primary:has-text("Sign in")')

        # Optionally take a screenshot
        await page.screenshot(path="screenshot.png")

        await page.wait_for_selector(
            ".text-center.message-screen.b-bubble-screen__spaced", timeout=10000
        )

        # Take a screenshot (optional)
        await page.screenshot(path="after-message.png")
        await browser.close()


def tado_login(username, password):
    tado = Tado(token_file_path=TOKEN_FILE_PATH)

    status = tado.device_activation_status()
    print (status)

    if status == "PENDING":
        url = tado.device_verification_url()

        asyncio.run(browser_login(url, username, password))

        tado.device_activation()

        status = tado.device_activation_status()

    if status == "COMPLETED":
        print("Login successful")
    else:
        print(f"Login status is {status}")

    return tado


def send_reading_to_tado(username, password, reading):
    """
    Sends the total consumption reading to Tado using its Energy IQ feature.
    """

    tado = tado_login(username=username, password=password)

    result = tado.set_eiq_meter_readings(reading=int(reading))
    print(result)


def parse_args():
    """
    Parses command-line arguments for Tado and Octopus API credentials and meter details.
    """
    parser = argparse.ArgumentParser(
        description="Tado and Octopus API Interaction Script"
    )

    # Tado API arguments
    parser.add_argument("--tado-email", required=False, help="Tado account email")
    parser.add_argument("--tado-password", required=False, help="Tado account password")

    # Octopus API arguments
    parser.add_argument(
        "--mprn",
        required=False,
        help="MPRN (Meter Point Reference Number) for the gas meter"
    )
    parser.add_argument(
        "--gas-serial-number", required=False, help="Gas meter serial number"
    )
    parser.add_argument("--octopus-api-key", required=False, help="Octopus API key")

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    tado = tado_login(username=args.tado_email, password=args.tado_password)
    
    token = tado.get_refresh_token()
    print (f"Token: {token}")
#    
    url = "https://login.tado.com/oauth2/token"
    data = {
        "client_id": "1bb50063-6b0c-4d11-bd99-387f4a91cc46",
        "grant_type": "refresh_token",
        "refresh_token": token
    }

    # pylint: disable=R0204
    
    resp = requests.post(url, params=data, data=json.dumps({}).encode("utf8"),
                         headers={'Content-Type': 'application/json',
                                            'Referer' : 'https://my.tado.com/'})

    with open(TOKEN_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {"refresh_token": resp.json()['refresh_token']},
            f,
        )


    # Get total consumption from Octopus Energy API
    consumption = get_meter_reading_total_consumption(
        args.octopus_api_key, args.mprn, args.gas_serial_number, resp.json()['access_token']
    )

    # Send the total consumption to Tado
#    send_reading_to_tado(TADO_USERNAME, TADO_PASSWORD, consumption)