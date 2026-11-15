# MODIS → VIIRS regressions and harmonized counts

This directory contains the notebook and functions used to estimate relationships between monthly MODIS and VIIRS hotspot counts by country and to generate a retrospective historical series on the VIIRS scale.

## Files

- `regressoes_modis_viirs_por_pais.ipynb`: initial comparison, global model fits, diagnostics, model storage, and monthly aggregate updates.
- `regression_pipeline.py`: data loading and validation, regression fitting, predictions, and persistence to DuckDB/CSV.
- `test_regression_pipeline.py`: tests for predictions, AQUA/TERRA selection, and CSV/DuckDB synchronization.
- `requirements.txt`: Python dependencies.

## Running the notebook

From the project root:

```bash
python -m pip install -r dataset_processing/regression/requirements.txt
jupyter lab dataset_processing/regression/regressoes_modis_viirs_por_pais.ipynb
```

The notebook locates these project files:

- `data/focos_america_sul.duckdb`
- `data/focos_mensais_america_sul.csv`

Restart the kernel and run all cells after updating the code or changing notebook versions, so that old functions retained in memory are not used.

## Modeling

### Objective

MODIS and VIIRS do not observe hotspots in the same way. VIIRS has finer spatial resolution and greater sensitivity, so it normally records more hotspots than MODIS in the same region. Combining the observations without correction would create an artificial break in the historical series when SNPP begins operating.

Our objective is to estimate how many hotspots SNPP would probably have recorded during months when only MODIS was available. We use months in which AQUA and SNPP operated at the same time, fit a relationship between their monthly counts, and apply that relationship retrospectively.

### Why Quasi-Poisson and Negative Binomial

The monthly number of hotspots is a count. A simple Poisson model assumes that, after accounting for the model variables, the count variance equals its mean. We have no basis for asserting that this equality holds for hotspots, which can vary greatly between months and exhibit extreme peaks.

We therefore test two families that allow greater dispersion than a simple Poisson model:

- **Quasi-Poisson:** allows the variance to be a multiple of the mean: `Var(Y|x) = phi × mean`.
- **Negative Binomial:** allows the variance to grow more rapidly: `Var(Y|x) = mean + alpha × mean²`.

These alternatives avoid imposing a mean-variance relationship that the data do not justify.

### Tested hypotheses

We did not know in advance which form would best represent the relationship between the AQUA count (`x`) and the SNPP count (`y`). Each family was therefore tested with three hypotheses for the expected mean:

| Hypothesis | Equation | Plain-language interpretation |
|---|---|---|
| Proportional | `mean = c × x` | SNPP always grows in the same proportion as AQUA. |
| Exponential | `mean = exp(beta0 + beta1 × x)` | The SNPP count can grow at an accelerating rate. |
| Power | `mean = c × (1 + x)^beta1` | The relationship is nonlinear but grows less explosively than the exponential relationship. |

With two families and three hypotheses, we compared six models for **Argentina / AQUA → SNPP**. The models were fitted to the 168 paired months from January 2012 through December 2025. Missing months were neither converted to zero nor fabricated.

### Why AQUA → SNPP

We chose AQUA as the primary source because the literature supports comparing Aqua MODIS observations with Suomi NPP VIIRS observations at nearby times and locations.

Zheng et al. (2026) combined the MYD14 product from Aqua MODIS with the VNP14IMG product from SNPP VIIRS. The study matched nearly simultaneous observations at the scale of the area observed by MODIS before performing fusion. Fu et al. (2020) also compared MODIS and VIIRS using nearly simultaneous observations in overlapping orbits. This reduces the risk of comparing fires observed at very different times.

Our procedure is simpler than those in the papers: we work with monthly country totals rather than direct pixel matching. The studies therefore support the comparability of AQUA and SNPP, but do not by themselves prove that our regression is perfect.

TERRA also receives its own model and is used whenever AQUA is unavailable for a country/month, regardless of year.

### Selection by lowest MAE

We selected **Quasi-Poisson + power** because this combination had the lowest MAE among the six candidates for Argentina.

MAE is the mean absolute error. It was selected as the primary criterion because:

- it is expressed directly in hotspots per month;
- it is easy to interpret as the model's typical monthly error;
- it gives errors linear weight;
- it is less dominated by a few extreme months than RMSE, which squares errors.

The comparison results were:

| Family | Hypothesis | MAE (hotspots/month) |
|---|---|---:|
| Quasi-Poisson | Power | **3,287.39** |
| Negative Binomial | Power | 3,313.72 |
| Quasi-Poisson | Proportional | 3,670.88 |
| Negative Binomial | Proportional | 4,116.89 |
| Quasi-Poisson | Exponential | 6,143.79 |
| Negative Binomial | Exponential | 12,278.38 |

The power Negative Binomial model had a slightly lower RMSE than the power Quasi-Poisson model, but it did not have the lowest MAE. Because our priority was to reduce the typical monthly absolute error, we retained the power Quasi-Poisson choice.

This comparison used the same data used to fit the models. It describes in-sample fit and does not guarantee that the configuration will have the lowest error on future data. Out-of-sample temporal validation is an important improvement for future versions.

### Argentina result

The selected model for **Argentina / AQUA → SNPP** was:

```text
Estimated SNPP = 14.0245071142 × (1 + AQUA)^0.886782242072
```

| Measure | Result |
|---|---:|
| Fit period | January 2012 to December 2025 |
| Months used | 168 |
| RMSE | 4,970.02 hotspots/month |
| MAE | 3,287.39 hotspots/month |
| Mean bias | 0.000000000059 hotspot/month |
| Largest absolute error | 19,260.15 hotspots |
| Date of largest error | January 2022 |
| Observed value on that date | 62,411 hotspots |
| Estimated value on that date | 43,150.85 hotspots |

The mean bias is effectively zero. This indicates that, in the fitting dataset, overestimates and underestimates canceled out on average. It does not mean that every month had a small error, as shown by the largest absolute error in January 2022.

### Application to the other countries

After selecting the Quasi-Poisson family and power hypothesis in Argentina, we applied the same combination to the other countries and to the AQUA → SNPP and TERRA → SNPP pairs.

Only the selected **structure** was reused. Each country and source satellite received its own coefficients, estimated from its own paired months. Argentina's coefficients were not copied to other countries.

The global configuration is **Quasi-Poisson + power**. It is fitted separately for each country and for both pairs targeting SNPP:

- AQUA → SNPP
- TERRA → SNPP

NOAA-20 remains in the observed data but does not participate in the regressions or the harmonized series. With the current 13 countries/territories, 26 equations are stored. The production coefficients are stored on the predictor's original scale in the `modelos_equacoes` table. Comparisons and metrics are calculated over months with paired observed data; missing data are not imputed during fitting.

### Limitations and future improvements

The current model uses monthly totals by country. This aggregation is simple and useful for constructing the first historical series, but it hides local differences in climate, terrain, vegetation, fire size, and satellite observation conditions.

Fu et al. (2020) showed that the detection difference between MODIS and VIIRS depends on land-cover type. Among hotspots detected by VIIRS, MODIS failed to detect 65% in forests and 83% in low-biomass areas such as agricultural areas, fields, and herbaceous vegetation. The study also found differences in the fire radiative power observed by the sensors.

An important improvement would be to include the vegetation-cover type at each hotspot location. Future versions could test:

- separate models by vegetation class;
- interactions between MODIS count and vegetation cover;
- spatial or hierarchical models with regional differences;
- observation-angle, cloud, and fire-radiative-power variables;
- more flexible machine-learning models;
- temporal validation by training on earlier years and testing on later years.

These extensions could better represent the sensitivity differences between MODIS and VIIRS in forests, agricultural areas, and low-biomass regions.

### References

- Zheng, Y. et al. (2026). *Fire Radiative Power Correction and Spatiotemporal Fusion Based on MYD14 and VNP14IMG*. Remote Sensing, 18(10), 1650. https://doi.org/10.3390/rs18101650
- Fu, Y.; Li, R.; Wang, X.; Bergeron, Y.; Valeria, O.; Chavardès, R. D.; Wang, Y.; Hu, J. (2020). *Fire Detection and Fire Radiative Power in Forests and Low-Biomass Lands in Northeast Asia: MODIS versus VIIRS Fire Products*. Remote Sensing, 12(18), 2870. https://doi.org/10.3390/rs12182870

## Harmonized VIIRS series

After validating all fits, the pipeline adds `nfocos_harm` and `modelo_harm` to the `focos_mensais` table and monthly CSV, and distributes values through the `peso_harm` column of the raw per-hotspot dataset.

- Throughout the full period, it calculates an SNPP prediction for each country/month with a MODIS count. AQUA is the preferred input; TERRA is used whenever AQUA does not exist for that country/month.
- Every prediction uses the model specific to the country and source MODIS satellite, including when an SNPP observation exists in the same month.
- `nfocos_harm` is rounded to the nearest integer; half values are rounded up. Coefficients, fits, and metrics retain their original precision.
- `modelo_harm` identifies `AQUA->SNPP` or `TERRA->SNPP` and the family/hypothesis actually used.
- MODIS rows retain the observed `nfocos` and leave both new columns null.
- Observed SNPP rows retain the detection count in `nfocos` and receive the independent MODIS-model prediction in `nfocos_harm`.
- When MODIS exists but there is no SNPP row, an SNPP row is created with null `nfocos` and a populated prediction, before or after 2012. These values are estimates, not observed FIRMS detections.
- NOAA-20 retains its observed `nfocos`, but its harmonized columns remain null. No synthetic NOAA-20 rows are created.
- Months without an AQUA/TERRA count have no harmonized value.

`peso_harm` represents the displayed spatial series: before 2012, each hotspot from the selected AQUA/TERRA source receives `nfocos_harm / nfocos_source`; from 2012 onward, each observed SNPP hotspot receives weight `1`. All other hotspots receive `0`. Consequently, before 2012 `SUM(peso_harm)` reproduces `nfocos_harm`; from 2012 onward it reproduces the observed SNPP `nfocos`. Recent model-only months without an SNPP observation have no spatial weight. The validation tolerance is `1e-5`, and NOAA-20 is never included in the sum.

Synthetic VIIRS rows do not participate in future fits: `load_monthly_counts` selects only records with an observed `nfocos`. Synthetic rows are rebuilt on every run, preventing duplicates.

`nfocos_harm` and `nfocos` are separate columns: the former is always a predicted count on the SNPP scale; the latter preserves the observed count or remains null in a synthetic SNPP row.

## Data persistence and regeneration

After calculating and validating the models, the notebook writes 26 models to `modelos_equacoes` and replaces `focos_mensais` and `focos_brutos` inside one DuckDB transaction. It prepares and validates the corresponding monthly and raw CSVs as temporary files, then coordinates their replacement with filesystem backups before committing the DuckDB transaction. On a pre-commit failure, it rolls back DuckDB and restores or removes the replaced CSVs as appropriate. This provides coordinated recovery, but it is not a single atomic transaction across DuckDB and both filesystem files. The observed `nfocos` sum and number of raw hotspots are preserved. No auxiliary prediction table is created.

The FIRMS notebook `dataset_processing/dataset_extractor/02_tratamento_firms.ipynb` creates empty derived columns during initial aggregation. If the monthly aggregate is regenerated from the raw files, rerun the regression notebook to recalculate `nfocos_harm`, reconstruct synthetic rows, and restore spatial weights. With monthly reprocessing disabled, the extraction workflow preserves `nfocos_harm`, `modelo_harm`, `modelos_equacoes`, and existing `peso_harm` only after exact observation and monthly-group reconciliation; it aborts on a mismatch.

## Tests

From the project root:

```bash
pytest -q
```

The tests cover AQUA priority, TERRA fallback, the selected power-form prediction, synthetic rows, half-up integer rounding, loading without null observations, interruption rollback, and equality between CSV and DuckDB. Full production reconciliation tests are skipped when complete source files are not in the expected directory.

## Updated data status

After the SNPP-only migration, the aggregate will contain predictions for every month with AQUA or TERRA, including after 2012 and when observed SNPP is absent. A total of 26 models (13 countries × 2 sources) will be persisted. Final totals depend on the FIRMS files and must be validated after execution.
