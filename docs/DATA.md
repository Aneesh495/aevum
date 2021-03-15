# Data sources and permissions

## UN World Population Prospects

The original 2024 revision supplies historical modeled estimates through 2023. The download filename contains “Medium” for the historical slice as well. The release period, rather than that column alone, determines whether a value is a projection. Only files explicitly ending in 1950–2023 are accepted for fitting. Geography follows the source location identity within the revision. The frozen frame includes 42 countries across six study regions and 54 calendar years. The region labels are study strata.

Section B of the methodology appendix defines the released person-years as the exposure recovered from the estimated deaths and the period mortality schedule. This reconstruction is not an independent registration estimate. The CSVs report both components in thousands. Conversion to absolute units uses the same factor for both. Cells rounded to zero exposure are kept with a diagnostic flag. Complete tables retain the original 100+ tail if it can be evaluated. Forecasts use exposure-weighted pooling at 90+ and sum counts and exposures before taking ratios.

The UN makes the files available as public downloads and releases the methodology under CC BY 3.0 IGO. Aevum keeps the source archives outside Git. Citation is United Nations, Department of Economic and Social Affairs, Population Division (2024), World Population Prospects 2024.

[Official release](https://population.un.org/wpp) · [Methodology](https://population.un.org/wpp/assets/Files/WPP2024_Methodology.pdf)

## WHO Mortality Database

The pinned data come from the February 2026 archive. WHO makes the files available for noncommercial research use. Source records remain outside Git. The figures in this repository credit WHO for supplying the data. Aevum's authors are responsible for the analyses and interpretations.

WHO population files contain midyear headcounts. Aevum never uses WPP modeled exposure as the denominator for WHO death counts. The source register distinguishes national tabulations from narrower registration coverage. Tabulated counts for the full territory do not by themselves establish registration completeness.

[Source and data-use guidelines](https://www.who.int/data/data-collection-tools/who-mortality-database) · [WHO usability criteria](https://platform.who.int/mortality/about/data-quality)

The historical-vintage comparison uses the official WPP 2022 archive. It matches source location identifiers to WPP 2024 and freezes 1970–2021 as the shared historical years. Official medium projections beginning in 2022 are excluded from the 2022 input and from the later target. [Vintage study](research/11-vintage.md)

The WHO quality screen uses the 2026 methods annex for the GHE 2023 release. It requires the latest reported adult completeness benchmark at or above 95% and usable age-5+ cause data. Reporting area exclusions follow the life-table methods' named geographic gaps. The latest benchmark is retained with its reported year and cannot certify every earlier registration period. [Completeness annex](https://cdn.who.int/media/docs/default-source/gho-documents/global-health-estimates/ghe2023_lifetable_methods.pdf) · [Cause quality annex](https://cdn.who.int/media/docs/default-source/gho-documents/global-health-estimates/ghe2023_cod_methods.pdf)
