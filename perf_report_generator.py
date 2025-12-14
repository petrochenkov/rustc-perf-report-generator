import pickle
from dataclasses import dataclass
from typing import Tuple

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.alert import Alert
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

BENCH_TABLE_CLASS = 'bench-table'


@dataclass
class BenchTable:
    name: str
    results: list['BenchmarkResult']


@dataclass
class BenchmarkResult:
    name: str
    profile: str
    scenario: str
    backend: str
    target: str
    change: float
    sig_threshold: float
    sig_factor: float
    before_raw: float
    after_raw: float

    @staticmethod
    def parse_from_row(raw_row: list[str]) -> 'BenchmarkResult':
        return BenchmarkResult(
            name=raw_row[1],
            profile=raw_row[2],
            scenario=raw_row[3],
            backend=raw_row[4],
            target=raw_row[5],
            change=BenchmarkResult.parse_number(raw_row[6][:-1]),
            sig_threshold=BenchmarkResult.parse_number(raw_row[7][:-1]),
            sig_factor=BenchmarkResult.parse_number(raw_row[8][:-1]),
            before_raw=BenchmarkResult.parse_number(raw_row[9]),
            after_raw=BenchmarkResult.parse_number(raw_row[10]),
        )

    @staticmethod
    def parse_number(s: str) -> float:
        return float(s.replace(',', ''))


def download_benchmarks_data(first_sha: str, second_sha: str, stat: str, tab: str) -> list[BenchTable]:
    url = construct_query_url(first_sha, second_sha, stat, tab)
    browser, alert_shown = download_url(url)

    if alert_shown:
        print(f'An alert was trigerred, commits {first_sha} and {second_sha} are invalid for comparison')
        return []

    return parse_benchmark_tables(browser)


def construct_query_url(first_sha: str, second_sha: str, stat: str, tab: str):
    base_url = 'https://perf.rust-lang.org/compare.html?'

    def add_query_param(base_url: str, key: str, value: str) -> str:
        return base_url + f'{key}={value}&'

    base_url = add_query_param(base_url, 'start', first_sha)
    base_url = add_query_param(base_url, 'end', second_sha)
    base_url = add_query_param(base_url, 'stat', stat)
    base_url = add_query_param(base_url, 'tab', tab)
    base_url = add_query_param(base_url, 'nonRelevant', 'true')
    base_url = add_query_param(base_url, 'showRawData', 'true')

    return base_url


def download_url(url: str) -> Tuple[WebDriver, bool]:
    print(f"Started downloading URL {url}")
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    browser = webdriver.Chrome(options=chrome_options)
    browser.get(url)

    bench_tables_ec = EC.presence_of_element_located((By.CLASS_NAME, BENCH_TABLE_CLASS))
    alert_present_ec = EC.alert_is_present()

    try:
        element = WebDriverWait(browser, timeout=5).until(EC.any_of(alert_present_ec, bench_tables_ec))
    except TimeoutException:
        print('Timeoutted while waiting for the page to load')
        exit(1)

    print('Finished downloading page')

    return browser, type(element) is Alert


def parse_benchmark_tables(browser: WebDriver) -> list[BenchTable]:
    elem = browser.find_element(value='app')
    tables = elem.find_elements(By.CLASS_NAME, BENCH_TABLE_CLASS)

    bench_tables = []
    for table in tables:
        table_id = table.get_attribute('id')
        try:
            table_body = table.find_element(By.TAG_NAME, 'tbody')
            rows = table_body.find_elements(By.TAG_NAME, 'tr')

            bench_results = []

            for row in rows:
                cols = row.find_elements(By.TAG_NAME, 'td')
                raw_row = list(map(lambda c: c.text, cols))
                bench_results.append(BenchmarkResult.parse_from_row(raw_row))

            bench_tables.append(BenchTable(
                name=table_id,
                results=bench_results
            ))
        except Exception:
            print(f'Table "{table_id}" does not contain parsable results, skipping it')

    return bench_tables


def read_commits_file(file_path: str) -> list[(str, str)]:
    with open(file_path, 'r') as fin:
        return list(map(lambda s: s.split(), fin.readlines()))


class AggregatedBenchData:
    def __init__(self, name: str, raw_values: dict[str, list[float]]):
        assert len(raw_values) > 0

        self.name = name
        self.values = dict(map(lambda p: (p[0], sum(p[1])), raw_values.items()))

        self.ordered_values = list(self.values.items())
        self.ordered_values.sort(key = lambda x: x[0])


    def to_csv_line(self) -> str:
        return f'{self.name};{";".join(map(lambda x: str(x[1]), self.ordered_values))}\n'

    def __repr__(self) -> str:
        return f'{self.name} = ({self.values})'


def serialize_results_to_csv(results: list[AggregatedBenchData], output_file_path: str):
    with open(output_file_path, 'w') as fout:
        fout.writelines([
            'Benchmark;SumChange;SumRawChange\n',
            *list(map(lambda r: r.to_csv_line(), results))
        ])


def aggregate_tables_data(tables: list[BenchTable], output_file_path: str):
    print('Started serializing results')

    benches_results: dict[str, dict[str, list[float]]] = {}

    for table in tables:
        for res in table.results:
            bench_full_name = '::'.join([table.name, res.name, res.profile, res.scenario])

            def get_or_create(d, key, default):
                if key not in d:
                    d[key] = default

                return d[key]

            bench_results =  get_or_create(benches_results, bench_full_name, {})
            get_or_create(bench_results, 'change', []).append(res.change)
            get_or_create(bench_results, 'raw_change', []).append(res.after_raw - res.before_raw)

    filtered_results = filter(lambda x: len(x[1]) > 0, benches_results.items())
    mapped_results = map(lambda x: AggregatedBenchData(x[0], x[1]), filtered_results)
    aggregated_results: list[AggregatedBenchData] = list(mapped_results)
    aggregated_results.sort(key=lambda a: a.values['change'])

    serialize_results_to_csv(aggregated_results, output_file_path)

    print(f'Serialized results to the output file {output_file_path}')


def download_tables(commits_file_path: str) -> list[BenchTable]:
    commits = read_commits_file(commits_file_path)
    tables = []

    for [from_commit, to_commit] in commits:
        print(f'Downloading commits data: {from_commit}, {to_commit}')

        tables.extend(download_benchmarks_data(
            from_commit,
            to_commit,
            'instructions:u',
            'compile'
        ))

        print('Downloaded commits data')

    return tables


def execute_download_command(commits_file_path: str, output_file_path: str):
    tables = download_tables(commits_file_path)

    with open(output_file_path, 'wb') as fout:
        pickle.dump(tables, fout)


def execute_aggregate_command(tables_file_path: str, output_file_path: str):
    with open(tables_file_path, 'rb') as fin:
        tables: list[BenchTable] = pickle.load(fin)

    aggregate_tables_data(tables, output_file_path)


def main():
    import sys

    command = sys.argv[1]

    if command == 'download':
        commits_file_path, output_file_path = sys.argv[2], sys.argv[3]
        execute_download_command(commits_file_path, output_file_path)
    elif command == 'aggregate':
        tables_file_path, output_file_path = sys.argv[2], sys.argv[3]
        execute_aggregate_command(tables_file_path, output_file_path)
    else:
        commits_file_path, output_file_path = sys.argv[1], sys.argv[2]
        tables = download_tables(commits_file_path)
        aggregate_tables_data(tables, output_file_path)


if __name__ == "__main__":
    main()
