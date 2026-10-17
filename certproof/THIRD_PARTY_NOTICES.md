# Third-party notices

## Bundled fonts (`backend/fonts/`)
All three families are published under the SIL Open Font License 1.1 (https://openfontlicense.org).

| Family | Files | Copyright holder (per upstream) |
| --- | --- | --- |
| Lora | `Lora-Variable.ttf`, `Lora-Italic-Variable.ttf` | The Lora Project Authors (Cyreal) |
| Poppins | `Poppins-Regular/Medium/Bold.ttf` | Indian Type Foundry |
| Inter | `Inter-Regular/Medium/SemiBold/Bold.otf` | The Inter Project Authors |

* `Inter-LICENSE.txt` is the licence/copyright file shipped with the Debian `fonts-inter` package these files came from.
* **Still to do before you redistribute this repository publicly:** add the upstream `OFL.txt` for Lora and Poppins next to
  the fonts. The build environment had no route to download them, so they are not included yet. Fonts are loaded locally
  only; nothing is fetched from a CDN.

## Python / JavaScript dependencies
Installed from PyPI/npm; see `requirements.lock.txt` and `frontend/package-lock.json` for exact versions and each
package's own licence. Notable: FastAPI, Pydantic, Playwright (Apache-2.0), pdfplumber/pdfminer.six (MIT), pypdf (BSD),
pypdfium2 (Apache-2.0/BSD), openpyxl (MIT), Pillow (HPND), fontTools (MIT), ReportLab (BSD; fixtures only), React (MIT).

## Models
The default model is `gemma3:4b`, an open-weight model run through your local Ollama. It is used under Google's Gemma
terms of use, not a public-domain or OSI-open-source licence. Weights are **not** included in this repository.
