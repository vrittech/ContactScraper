# ContactScraper

## NOTE:

> IMPORTANT: requires `selenium` and `requests`

> IMPORTANT: requires `Firefox` (selenium runs on ff)

> IMPORTANT: requires `git` installed; Install git [here](https://git-scm.com/install/windows)

> `scraper_v3.py` contains the finalized, multi-thread capable code

## Easily Running the GUI

- In Windows PowerShell, run:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

- Download the repository (Check the `Code` Green button at top-right), extract the folder, and **open powershell in the same folder**

***OR if git is installed***
```powershell
git clone https://github.com/vrittech/ContactScraper
cd ContactScraper/
```

- Finally, run the following in `powershell`:

`uv run scraper_multi_gui.py` in the ContactScraper folder





## Running the script locally

I've added instructions for Linux/MacOS machines primarily 

### Using `uv` (Recommended)

`uv` is a blazing-fast python package manager written in Rust. Using `uv` should be the norm! *(i love `uv`)*

#### Linux/macOS

##### `uv` installation

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # install uv
```
> You may need to restart your shell for `uv` to start working properly

#### Windows

#### `uv` installation

In PowerShell, run:
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

##### Local setup

```bash
git clone https://github.com/vrittech/ContactScraper.git
cd ContactScraper/
uv sync
```

For extracting contact info from a URL:
`uv run scraper_v3.py -u "<URL>"`
> Example: `uv run scraper_v3.py -u "https://ku.edu.np"`

For extracting contact info from keywords:
`uv run scraper_v3.py -k "<KEYWORDS>"`
> Example: `uv run scraper_v3.py -k "Software Companies in Kathmandu"`


### Using `pip`


#### Linux/macOS and Windows too(?)

##### Local setup + running

```bash
git clone https://github.com/vrittech/ContactScraper.git
cd ContactScraper/
python3 -m virtualenv .venv    # BEFORE RUNNING: ensure that virtualenv package is installed
source ./.venv/bin/activate
pip3 install -r requirements.txt     # or pip instead of pip3, whatever it's called
```

For extracting contact info from a URL:
`python3 scraper_v3.py -u "<URL>"`
> Example: `python3 scraper_v3.py -u "https://ku.edu.np"`

For extracting contact info from keywords:
`python3 scraper_v3.py -k "<KEYWORDS>"`
> Example: `python3 scraper_v3.py -k "Software Companies in Kathmandu"`


# Saving the extracted Contact Info
## CSV and JSON Files
Append the above scripts with a `-l` flag and the info is saved at `<current_dir>/json_data/contact__<time>.json` or `.csv`

# Limit Output Numbers
Using the `-n` flag, you can limit the number of websites scraped; for instance:

> Example: `python3 scraper_v3.py -k "Software Companies in Kathmandu" -n 10`

Above example Scrapes only 10 websites

# GUI
**UNDER DEVELOPMENT**
You can run the basic Tk based GUI using 

`uv run scraper_multi_gui.py`

OR, if running through `pip`,

`python3 run scraper_multi_gui.py`
