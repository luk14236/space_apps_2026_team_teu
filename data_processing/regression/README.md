# Regressões MODIS → VIIRS e contagens harmonizadas

Este diretório contém o notebook e as funções para estimar relações entre as contagens mensais de focos MODIS e VIIRS por país e para gerar uma série histórica retrospectiva na escala de VIIRS.

## Arquivos

- `regressoes_modis_viirs_por_pais.ipynb`: comparação inicial, ajustes globais, diagnósticos, gravação dos modelos e atualização do agregado mensal.
- `regression_pipeline.py`: carregamento e validação dos dados, ajuste das regressões, previsões e persistência no DuckDB/CSV.
- `test_regression_pipeline.py`: testes das previsões, da seleção AQUA/TERRA e da sincronização CSV/DuckDB.
- `requirements.txt`: dependências Python.

## Executar

A partir da raiz do projeto:

```bash
python -m pip install -r dataprocessing/regression/requirements.txt
jupyter lab dataprocessing/regression/regressoes_modis_viirs_por_pais.ipynb
```

O notebook localiza estes arquivos do projeto:

- `data/focos_america_sul.duckdb`
- `data/focos_mensais_america_sul.csv`

Reinicie o kernel e execute todas as células após atualizar o código ou trocar de versão do notebook, para evitar funções antigas mantidas em memória.

## Modelagem

### Objetivo

MODIS e VIIRS não enxergam os focos de calor da mesma forma. O VIIRS tem resolução espacial mais fina e maior sensibilidade, por isso normalmente registra mais focos que o MODIS na mesma região. Juntar as observações sem correção criaria uma quebra artificial na série histórica quando o SNPP começa a operar.

Nosso objetivo é estimar quantos focos o SNPP provavelmente registraria nos meses em que só havia MODIS. Para isso, usamos os meses em que AQUA e SNPP operaram ao mesmo tempo, ajustamos uma relação entre suas contagens mensais e aplicamos essa relação retrospectivamente.

### Por que Quasi-Poisson e Binomial Negativa

O número mensal de focos é uma contagem. Um modelo de Poisson simples pressupõe que, depois de considerar as variáveis do modelo, a variância da contagem seja igual à sua média. Não temos base para afirmar que essa igualdade vale para focos de calor, que podem variar muito entre meses e apresentar picos extremos.

Por isso, testamos duas famílias que permitem dispersão maior que a do Poisson simples:

- **Quasi-Poisson:** permite que a variância seja uma múltipla da média: `Var(Y|x) = phi × media`.
- **Binomial Negativa:** permite que a variância cresça mais rapidamente: `Var(Y|x) = media + alpha × media²`.

Essas duas alternativas evitam forçar uma relação entre média e variância que não conseguimos justificar com os dados.

### Hipóteses testadas

Não sabíamos previamente qual formato representaria melhor a relação entre a contagem AQUA (`x`) e a contagem SNPP (`y`). Por isso, cada família foi testada com três hipóteses para a média esperada:

| Hipótese | Equação | Interpretação simples |
|---|---|---|
| Proporcional | `media = c × x` | O SNPP cresce sempre na mesma proporção do AQUA. |
| Exponencial | `media = exp(beta0 + beta1 × x)` | A contagem SNPP pode crescer de forma acelerada. |
| Potencial | `media = c × (1 + x)^beta1` | A relação é não linear, mas cresce de forma menos explosiva que a exponencial. |

Com duas famílias e três hipóteses, comparamos seis modelos para **Argentina / AQUA → SNPP**. Os modelos foram ajustados nos 168 meses pareados entre janeiro de 2012 e dezembro de 2025. Meses ausentes não foram transformados em zero nem inventados.

### Por que AQUA → SNPP

Escolhemos AQUA como origem principal porque há suporte na literatura para comparar observações do Aqua MODIS com o Suomi NPP VIIRS em horários e locais próximos.

Zheng et al. (2026) combinaram os produtos MYD14, do Aqua MODIS, e VNP14IMG, do SNPP VIIRS. O trabalho fez correspondência de observações quase simultâneas na escala da área observada pelo MODIS antes de realizar a fusão. Fu et al. (2020) também compararam MODIS e VIIRS usando observações quase simultâneas em órbitas sobrepostas. Isso reduz o risco de comparar incêndios observados em momentos muito diferentes.

Nosso procedimento é mais simples que o dos artigos: trabalhamos com totais mensais por país, e não com correspondência direta entre pixels. Portanto, os estudos sustentam a comparabilidade entre AQUA e SNPP, mas não provam, por si só, que nossa regressão seja perfeita.

TERRA também recebe um modelo próprio para ser usado antes de 2012 quando AQUA não está disponível naquele país e mês.

### Escolha pelo menor MAE

Escolhemos **Quasi-Poisson + potencial** porque essa combinação apresentou o menor MAE entre os seis candidatos da Argentina.

O MAE é a média do valor absoluto dos erros. Ele foi escolhido como critério principal porque:

- é expresso diretamente em focos por mês;
- é fácil de interpretar como o erro mensal típico do modelo;
- dá peso linear aos erros;
- é menos dominado por poucos meses extremos que o RMSE, que eleva os erros ao quadrado.

Os resultados da comparação foram:

| Família | Hipótese | MAE (focos/mês) |
|---|---|---:|
| Quasi-Poisson | Potencial | **3.287,39** |
| Binomial Negativa | Potencial | 3.313,72 |
| Quasi-Poisson | Proporcional | 3.670,88 |
| Binomial Negativa | Proporcional | 4.116,89 |
| Quasi-Poisson | Exponencial | 6.143,79 |
| Binomial Negativa | Exponencial | 12.278,38 |

A Binomial Negativa potencial teve RMSE ligeiramente menor que a Quasi-Poisson potencial, mas não teve o menor MAE. Como nossa prioridade foi reduzir o erro absoluto mensal típico, mantivemos a escolha Quasi-Poisson potencial.

Essa comparação foi feita nos mesmos dados usados para ajustar os modelos. Ela descreve o ajuste dentro da amostra e não garante que a configuração terá o menor erro em dados futuros. Uma validação temporal fora da amostra é uma melhoria importante para as próximas versões.

### Resultado da Argentina

O modelo selecionado para **Argentina / AQUA → SNPP** foi:

```text
SNPP estimado = 14,0245071142 × (1 + AQUA)^0,886782242072
```

| Medida | Resultado |
|---|---:|
| Período do ajuste | janeiro/2012 a dezembro/2025 |
| Meses usados | 168 |
| RMSE | 4.970,02 focos/mês |
| MAE | 3.287,39 focos/mês |
| Viés médio | 0,000000000059 foco/mês |
| Maior erro absoluto | 19.260,15 focos |
| Data do maior erro | janeiro/2022 |
| Valor observado nessa data | 62.411 focos |
| Valor estimado nessa data | 43.150,85 focos |

O viés médio é praticamente zero. Isso indica que, no conjunto usado para o ajuste, superestimações e subestimações se compensaram em média. Isso não significa que todos os meses tenham erro pequeno, como mostra o maior erro absoluto de janeiro de 2022.

### Aplicação aos demais países

Depois de escolher a família Quasi-Poisson e a hipótese potencial na Argentina, aplicamos essa mesma combinação aos demais países e aos pares AQUA → SNPP e TERRA → SNPP.

Reutilizamos apenas a **estrutura** escolhida. Cada país e cada satélite de origem recebeu seus próprios coeficientes, estimados com seus próprios meses pareados. Os coeficientes da Argentina não foram copiados para os outros países.

A configuração global é **Quasi-Poisson + potencial**. Ela é ajustada separadamente para cada país e para os dois pares com destino SNPP:

- AQUA → SNPP
- TERRA → SNPP

NOAA-20 permanece nos dados observados, mas não participa das regressões nem da série harmonizada. Com os 13 países/territórios atuais, são gravadas 26 equações. Os coeficientes usados em produção ficam na escala original do preditor, na tabela `modelos_equacoes`. A comparação e as métricas são calculadas sobre os meses com dados observados pareados; os dados ausentes não são imputados no ajuste.

### Limitações e melhorias futuras

O modelo atual usa totais mensais por país. Essa agregação é simples e útil para construir a primeira série histórica, mas esconde diferenças locais de clima, relevo, vegetação, tamanho do incêndio e condições de observação do satélite.

Fu et al. (2020) mostraram que a diferença de detecção entre MODIS e VIIRS depende do tipo de cobertura. Entre os focos detectados pelo VIIRS, o MODIS não detectou 65% em florestas e 83% em áreas de baixa biomassa, como áreas agrícolas, campos e vegetação herbácea. O estudo também encontrou diferenças na potência radiativa observada pelos sensores.

Uma melhoria importante é incluir o tipo de cobertura vegetal do local do foco. Versões futuras podem testar:

- modelos separados por classe de vegetação;
- interação entre contagem MODIS e cobertura vegetal;
- modelos espaciais ou hierárquicos, com diferenças por região;
- variáveis de ângulo de observação, nuvens e potência radiativa do fogo;
- modelos mais flexíveis de aprendizado de máquina;
- validação temporal, treinando em anos anteriores e testando em anos posteriores.

Essas extensões podem representar melhor a diferença de sensibilidade entre MODIS e VIIRS em florestas, áreas agrícolas e regiões de baixa biomassa.

### Referências

- Zheng, Y. et al. (2026). *Fire Radiative Power Correction and Spatiotemporal Fusion Based on MYD14 and VNP14IMG*. Remote Sensing, 18(10), 1650. https://doi.org/10.3390/rs18101650
- Fu, Y.; Li, R.; Wang, X.; Bergeron, Y.; Valeria, O.; Chavardès, R. D.; Wang, Y.; Hu, J. (2020). *Fire Detection and Fire Radiative Power in Forests and Low-Biomass Lands in Northeast Asia: MODIS versus VIIRS Fire Products*. Remote Sensing, 12(18), 2870. https://doi.org/10.3390/rs12182870

## Série VIIRS harmonizada

Após validar todos os ajustes, o pipeline acrescenta `nfocos_harm` e `modelo_harm` à tabela `focos_mensais` e ao CSV mensal, e distribui os valores na coluna `peso_harm` do agregado bruto por foco.

- Em todo o período, calcula uma previsão SNPP por país/mês com contagem MODIS. AQUA é a entrada prioritária; TERRA é usado quando AQUA não existe naquele país/mês.
- Cada previsão usa o modelo específico do país e satélite MODIS de origem, inclusive quando existe uma observação SNPP no mesmo mês.
- `nfocos_harm` é arredondada para o inteiro mais próximo; meios valores são arredondados para cima. Os coeficientes, ajustes e métricas continuam usando a precisão original.
- `modelo_harm` identifica `AQUA->SNPP` ou `TERRA->SNPP` e a família/hipótese realmente usada.
- Linhas MODIS mantêm `nfocos` observado e deixam as duas colunas novas nulas.
- Linhas SNPP observadas mantêm a detecção em `nfocos` e recebem em `nfocos_harm` a previsão independente do modelo MODIS.
- Quando há MODIS, mas não há linha SNPP, é criada uma linha SNPP com `nfocos` nulo e previsão preenchida, antes ou depois de 2012. Esses valores são estimativas, não detecções FIRMS observadas.
- NOAA-20 mantém `nfocos` observado, mas suas colunas harmonizadas ficam nulas. Não são criadas linhas sintéticas NOAA-20.
- Meses sem contagem AQUA/TERRA ficam sem valor harmonizado.

`peso_harm` representa a série espacial exibida: antes de 2012, cada foco AQUA/TERRA da origem selecionada recebe `nfocos_harm / nfocos_origem`; desde 2012, cada foco SNPP observado recebe peso `1`. Todos os demais focos recebem `0`. Assim, antes de 2012 `SUM(peso_harm)` reproduz `nfocos_harm`; desde 2012 reproduz `nfocos` SNPP observado. Meses recentes apenas estimados, sem observação SNPP, não possuem peso espacial. A tolerância de validação é `1e-5` e NOAA-20 nunca é somado.

Linhas VIIRS sintéticas não participam de ajustes futuros: `load_monthly_counts` seleciona apenas registros com `nfocos` observado. Em cada execução, as linhas sintéticas são reconstruídas, evitando duplicações.

`nfocos_harm` e `nfocos` são colunas separadas: a primeira é sempre uma contagem prevista na escala SNPP; a segunda preserva a contagem observada, ou fica nula em uma linha SNPP sintética.

## Persistência e regeneração dos dados

Após calcular e validar os modelos, o notebook publica 26 modelos em `modelos_equacoes`, atualiza `focos_mensais` e `focos_brutos` dentro de uma transação DuckDB e grava os dois CSVs correspondentes. A soma observada de `nfocos` e a quantidade de focos brutos são preservadas. Não é criada tabela auxiliar para as previsões.

O notebook FIRMS `dataprocessing/dataset_extractor/02_tratamento_firms.ipynb` cria as colunas derivadas vazias na agregação inicial. Se a agregação mensal for regenerada a partir dos arquivos brutos, execute novamente o notebook de regressões para recalcular `nfocos_harm` e reconstruir as linhas sintéticas. Ao reconstruir o DuckDB, o fluxo preserva `modelos_equacoes` quando essa tabela já existe.

## Testes

Na raiz do projeto:

```bash
pytest -q
```

Os testes cobrem a prioridade AQUA, fallback TERRA, fórmulas, linhas sintéticas, arredondamento inteiro, carregamento sem observações nulas e igualdade entre CSV e DuckDB. Alguns testes de reconciliação integral são ignorados quando os arquivos completos de origem não estão no diretório esperado.

## Estado dos dados atualizado

Após a migração SNPP-only, o agregado terá previsões em todos os meses com AQUA ou TERRA, inclusive depois de 2012 e na ausência de SNPP observado. Serão persistidos 26 modelos (13 países × 2 origens). Os totais finais dependem dos arquivos FIRMS e devem ser validados após a execução.
