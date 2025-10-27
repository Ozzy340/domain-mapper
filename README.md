Domain Redirect Mapper

Domain Redirect Mapper is a Python tool that reads a list of domains or subdomains from a CSV file, sequentially loads each one in a real browser (via Playwright) to follow server and JavaScript redirects, and outputs a CSV mapping each source domain to its final destination.

It also counts how many input domains redirect to each destination and identifies whether a given destination is also part of the original input list.

⸻

🚀 Features
	•	Full Redirect Tracking — Follows both HTTP and JavaScript-based redirects using a headless Chromium browser.
	•	Sequential Processing — Handles one domain at a time for predictable performance and rate limiting.
	•	Smart Fallbacks — Tries HTTPS first, then falls back to HTTP automatically.
	•	Aggregated Destination Counts — Shows how many of your input domains redirect to the same target domain.
	•	In-List Detection — Flags if a destination is also part of the input list.
	•	Configurable Granularity — Choose to group counts by registrable domain (e.g. example.co.uk) or full hostname (e.g. www.example.co.uk).

⸻

📦 Installation

1. Clone the repository

git clone https://github.com/yourusername/domain-redirect-mapper.git
cd domain-redirect-mapper

2. Create a virtual environment

python -m venv .venv
source .venv/bin/activate   # On Windows: .venv\\Scripts\\activate

3. Install dependencies

pip install playwright tldextract
playwright install chromium


⸻

🧭 Usage

Basic command

python domain_redirect_mapper.py input.csv -o output.csv

Arguments

Argument	Description	Default
input_csv	Path to the CSV file containing domains or subdomains.	Required
-o, --output-csv	Output CSV file path.	redirect_map.csv
--timeout	Navigation timeout (ms).	15000
--js-settle	Time to wait for JS redirects (ms).	2000
--count-by	How to group destination counts — registrable or host.	registrable
--user-agent	Custom user agent string.	Chromium default
--ignore-https-errors	Ignore SSL certificate errors.	False

Input CSV format

The input CSV can either have a header named url or domain, or just a single column of domains.

Example:

domain
example.com
sub.example.com
redirected-site.net

Or without headers:

example.com
sub.example.com
redirected-site.net

Output CSV format

source_url	destination_url	pointing_to_count	points_to_list_domain
example.com	https://target.com/	2	False
another.com	https://example.com/	1	True


⸻

🧠 How It Works
	1.	The script reads each domain from your CSV file.
	2.	It uses Playwright (headless Chromium) to load each page sequentially.
	3.	The browser follows server redirects, meta-refreshes, and JavaScript redirects.
	4.	The final URL is recorded for each source domain.
	5.	It aggregates results to count how many input domains redirect to the same final destination.
	6.	The results are exported to a new CSV file.

⸻

⚙️ Example Workflow

python domain_redirect_mapper.py domains.csv --count-by registrable --timeout 20000

Sample Output:

[1/10] Resolving example.com ...
[2/10] Resolving testdomain.net ...
...
Done. Wrote 10 rows to redirect_map.csv.
3 source(s) point to a domain in the input list (by registrable match).

redirect_map.csv:

source_url,destination_url,pointing_to_count,points_to_list_domain
example.com,https://targetsite.com/,2,False
testdomain.net,https://example.com/,1,True


⸻

🧩 Troubleshooting
	•	Playwright not installed: Run pip install playwright && playwright install chromium.
	•	Timeouts: Increase --timeout if slow-loading pages are being skipped.
	•	Certificate errors: Add --ignore-https-errors if you’re testing self-signed or staging domains.
	•	JavaScript redirects missed: Increase --js-settle to give the page more time.

⸻

🧾 License

MIT License — You are free to use, modify, and distribute this software under the terms of the MIT License.

MIT License

Copyright (c) 2025 [Your Name or Organization]

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.


⸻

🤝 Contributing

Contributions, issues, and feature requests are welcome!
	1.	Fork the repository.
	2.	Create your feature branch (git checkout -b feature/my-feature).
	3.	Commit your changes (git commit -am 'Add new feature').
	4.	Push to your branch (git push origin feature/my-feature).
	5.	Open a Pull Request.

⸻

🧑‍💻 Author

Domain Redirect Mapper was created by ozzy_340@yahoo.co.uk Feel free to reach out with suggestions or improvements!