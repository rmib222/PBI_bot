# SPEC.md — PBI_bot: AdventureWorks Sales Analytics Bot

## 1. Mapeo de Arquitectura ($0 Headless Architecture)

```
┌─────────────────────────────────────────────────┐
│  FUENTE DE DATOS                                │
│  .pbip / TMDL  (AdventureWorks Sales.SemanticModel) │
│  → definition/tables/*.tmdl                     │
│  → definition/relationships.tmdl                │
└────────────────────┬────────────────────────────┘
                     │ inspección de metadatos
                     ▼
┌─────────────────────────────────────────────────┐
│  GENERADOR DE DATOS SINTÉTICOS                  │
│  bot_engine.py::generate_synthetic_data()       │
│  Genera DataFrames en memoria que replican      │
│  la estructura de las 5 entidades               │
└────────────────────┬────────────────────────────┘
                     │ DataFrames → DuckDB :memory:
                     ▼
┌─────────────────────────────────────────────────┐
│  MOTOR DE CONSULTA (DuckDB headless)            │
│  bot_engine.py::QueryEngine                     │
│  • Registra tablas en DuckDB en memoria         │
│  • Ejecuta SQL analítico (aggregations, joins)  │
│  • Formatea respuestas en texto/Markdown        │
└────────────────────┬────────────────────────────┘
                     │ answer: str
                     ▼
┌─────────────────────────────────────────────────┐
│  TELEGRAM BOT (python-telegram-bot)             │
│  telegram_bot.py                                │
│  • /start, /help → comandos base               │
│  • Texto libre → enrutamiento NL a motor        │
│  • Respuesta formateada → usuario              │
└────────────────────┬────────────────────────────┘
                     │ (futuro) deploy
                     ▼
┌─────────────────────────────────────────────────┐
│  VERCEL (opcional, fase futura)                 │
│  Webhook HTTP → telegram_bot.py                 │
└─────────────────────────────────────────────────┘
```

**Flujo de datos completo:**
1. `telegram_bot.py` recibe mensaje de usuario vía Telegram API
2. Extrae la pregunta y la pasa a `bot_engine.QueryEngine.answer(question)`
3. `QueryEngine` mapea la pregunta a una consulta SQL predefinida
4. DuckDB ejecuta la consulta sobre los datos sintéticos en memoria
5. El resultado se formatea como texto Markdown
6. `telegram_bot.py` envía la respuesta al usuario

---

## 2. Especificación del Modelo Semántico

### Entidades (5 tablas core)

#### Entidad 1: Sales (Ventas) — Tabla de hechos
| Columna | Tipo | Descripción |
|---------|------|-------------|
| SalesOrderLineKey | int64 | PK de línea de pedido |
| ResellerKey | int64 | FK → Reseller |
| CustomerKey | int64 | FK → Customer |
| ProductKey | int64 | FK → Product |
| OrderDateKey | int64 | FK → Date (orden) |
| SalesTerritoryKey | int64 | FK → Sales Territory |
| Order Quantity | int64 | Unidades vendidas |
| Unit Price | float | Precio unitario |
| Total Product Cost | float | Costo total del producto |
| Sales Amount | float | Ingreso total de la línea |

**Medidas clave:**
- `Sales = SUM(Sales Amount)`
- `Cost = SUM(Total Product Cost)`
- `Profit = Sales - Cost`
- `Profit % = Profit / Sales`
- `Orders = DISTINCTCOUNT(SalesOrderLineKey)`

#### Entidad 2: Customer (Clientes)
| Columna | Tipo | Descripción |
|---------|------|-------------|
| CustomerKey | int64 | PK |
| Customer ID | string | ID fuente |
| Customer | string | Nombre del cliente |
| City | string | Ciudad |
| State-Province | string | Estado/Provincia |
| Country-Region | string | País/Región |
| Postal Code | string | Código postal |

#### Entidad 3: Reseller (Vendedores/Distribuidores)
| Columna | Tipo | Descripción |
|---------|------|-------------|
| ResellerKey | int64 | PK |
| Reseller ID | string | ID fuente |
| Business Type | string | Tipo de negocio |
| Reseller | string | Nombre del revendedor |
| City | string | Ciudad |
| State-Province | string | Estado/Provincia |
| Country-Region | string | País/Región |

#### Entidad 4: Sales Territory (Regiones)
| Columna | Tipo | Descripción |
|---------|------|-------------|
| SalesTerritoryKey | int64 | PK |
| Region | string | Región de ventas |
| Country | string | País |
| Group | string | Grupo (ej. North America) |

#### Entidad 5: Product (Productos)
| Columna | Tipo | Descripción |
|---------|------|-------------|
| ProductKey | int64 | PK |
| SKU | string | Código SKU |
| Product | string | Nombre del producto |
| Standard Cost | float | Costo estándar |
| Color | string | Color |
| List Price | float | Precio de lista |
| Model | string | Modelo |
| Subcategory | string | Subcategoría |
| Category | string | Categoría |

### Relaciones
```
Sales.CustomerKey       → Customer.CustomerKey       (N:1)
Sales.ProductKey        → Product.ProductKey         (N:1)
Sales.ResellerKey       → Reseller.ResellerKey       (N:1)
Sales.SalesTerritoryKey → Sales Territory.SalesTerritoryKey (N:1)
```

---

## 3. Especificación del Golden Dataset

### Dataset Sintético
El motor genera datos sintéticos deterministas con seed fijo:
- **500 clientes** (Customer)
- **200 productos** en 3 categorías: Bikes, Components, Accessories
- **50 resellers** en 3 tipos: Specialty Bike Shop, Value Added Reseller, Warehouse
- **10 territorios** en 3 grupos: North America, Europe, Pacific
- **5,000 filas de ventas** (Sales), años 2020–2023

### 10 Preguntas del Golden Dataset

| # | Pregunta | SQL / Lógica | Criterio de Aceptación |
|---|----------|--------------|------------------------|
| Q1 | ¿Cuál es el total de ventas? | `SELECT SUM("Sales Amount") FROM sales` | Valor > 0, tipo float, formato "$X,XXX,XXX" |
| Q2 | ¿Cuál es la ganancia total? | `SELECT SUM("Sales Amount") - SUM("Total Product Cost") FROM sales` | Valor > 0, tipo float |
| Q3 | ¿Cuál es el margen de ganancia %? | `SELECT (SUM("Sales Amount") - SUM("Total Product Cost")) / SUM("Sales Amount") * 100 FROM sales` | Entre 0% y 100%, tipo float |
| Q4 | ¿Cuántos clientes únicos hay? | `SELECT COUNT(DISTINCT "CustomerKey") FROM sales` | Igual a nro. clientes en tabla Customer |
| Q5 | ¿Cuántos pedidos hay? | `SELECT COUNT(DISTINCT "SalesOrderLineKey") FROM sales` | Entero > 0, <= 5000 |
| Q6 | ¿Cuál es la categoría de producto con más ventas? | `SELECT p.Category, SUM(s."Sales Amount") ... GROUP BY p.Category ORDER BY 2 DESC LIMIT 1` | Una de: {Bikes, Components, Accessories} |
| Q7 | ¿Cuál es el territorio con más ventas? | `SELECT st.Region, SUM(s."Sales Amount") ... GROUP BY st.Region ORDER BY 2 DESC LIMIT 1` | Uno de los 10 territorios definidos |
| Q8 | ¿Cuántas unidades se vendieron en total? | `SELECT SUM("Order Quantity") FROM sales` | Entero > 0 |
| Q9 | ¿Cuál es el promedio de ventas por pedido? | `SELECT SUM("Sales Amount") / COUNT(DISTINCT "SalesOrderLineKey") FROM sales` | Float > 0 |
| Q10 | ¿Cuál es el top 3 de clientes por ventas? | `SELECT c.Customer, SUM(s."Sales Amount") ... GROUP BY c.Customer ORDER BY 2 DESC LIMIT 3` | Lista de 3 nombres, ordenada desc por monto |

### Criterios de Aceptación Globales
- Todos los valores numéricos deben ser reproducibles con `RANDOM_SEED=42`
- Las 10 preguntas deben retornar respuesta en < 2 segundos
- El formato de respuesta debe ser texto legible por humanos
- Los tests de pytest deben pasar con exit code 0

---

## 4. Definición de Interfaz y Variables

### Estructura de Respuestas Telegram

```python
# Respuesta simple (número/texto)
"💰 Total de Ventas: $12,345,678"

# Respuesta de ranking (Top N)
"🏆 Top 3 Clientes por Ventas:\n1. Cliente A — $1,234,567\n2. Cliente B — $987,654\n3. Cliente C — $765,432"

# Respuesta de porcentaje
"📈 Margen de Ganancia: 32.5%"

# Error / pregunta no reconocida
"❓ No entendí la pregunta. Prueba con:\n• total de ventas\n• ganancia total\n• top clientes\n• ventas por categoría"
```

### Contrato del archivo `.env`

```dotenv
# Token del bot de Telegram (obligatorio)
TELEGRAM_BOT_TOKEN="<token>"

# Seed para reproducibilidad del dataset sintético
RANDOM_SEED=42

# Número de filas de ventas a generar
SYNTHETIC_ROWS=5000

# Modo de ejecución: "polling" | "webhook"
BOT_MODE=polling
```

### Contrato de `bot_engine.QueryEngine`

```python
class QueryEngine:
    def __init__(self, seed: int = 42, n_rows: int = 5000) -> None: ...
    def answer(self, question: str) -> str:
        """
        Recibe pregunta en lenguaje natural.
        Retorna respuesta formateada como string.
        Lanza ValueError si la pregunta no se reconoce.
        """
```

### Estructura de Archivos del Proyecto

```
PBI_bot/
├── SPEC.md                          # Este documento
├── .env                             # Variables de entorno (NO en git)
├── .gitignore
├── requirements.txt
├── bot_engine.py                    # Motor DuckDB headless
├── telegram_bot.py                  # Interfaz Telegram
├── tests/
│   ├── __init__.py
│   └── golden_dataset.json          # 10 preguntas + valores esperados
│   └── test_golden.py               # Suite pytest
├── .github/
│   └── workflows/
│       └── test_golden.yml          # CI/CD GitHub Actions
└── pbi_model/                       # Copia del modelo TMDL
    └── definition/
        └── tables/
            ├── Sales.tmdl
            ├── Customer.tmdl
            ├── Product.tmdl
            ├── Reseller.tmdl
            └── Sales Territory.tmdl
```
