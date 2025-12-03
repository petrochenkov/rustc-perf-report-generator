def generate_report():
    pass

def download_commits_data(first_sha: str, second_sha: str, stat: str, tab: str):
    base_url = 'https://perf.rust-lang.org/compare.html?'

    def add_query_param(base_url: str, key: str, value: str):
        base_url += f'{key}={value}&'

    add_query_param(base_url, 'start', first_sha)
    add_query_param(base_url, 'end', second_sha)
    add_query_param(base_url, 'stat', stat)
    add_query_param(base_url, 'tab', tab)

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    browser = webdriver.Chrome(options=chrome_options)
    browser.get(base_url)

    import time
    time.sleep(1)

    elem = browser.find_element(value = "app")

    print(elem.get_attribute('innerHTML'))

download_commits_data(
    '0f6dae4afc8959262e7245fddfbdfc7a1de6f34a',
    '80d8f292d82d735f83417221dd63b0dd2bbb8dd2',
    'faults',
    'compile'
)
