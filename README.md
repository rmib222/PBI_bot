# PBI Bot

Bot de Telegram para consultas analíticas en lenguaje natural sobre el modelo semántico **AdventureWorks Sales** de Power BI.

## Arquitectura

El bot corre de forma nativa dentro de **OpenClaw** como una segunda cuenta de Telegram (`pbi`). No hay ningún script Python que mantener ni proceso externo que arrancar — OpenClaw levanta el bot automáticamente al iniciarse.

```
Usuario (Telegram) → OpenClaw (canal pbi) → gpt-5.4-nano + MCP Power BI → respuesta
```

### Componentes

| Componente | Descripción |
|---|---|
| OpenClaw canal `pbi` | Recibe mensajes del bot de Telegram y los enruta al agente |
| `gpt-5.4-nano` | Modelo de lenguaje eficiente y económico |
| MCP Power BI (`powerbi-modeling`) | Ejecuta DAX real contra el modelo semántico local |
| Skill `pbi-adventureworks-dax` | Esquema completo + patrones DAX para reducir turns por pregunta |
| `pbi_model/` | Definición TMDL del modelo (referencia, no se usa en ejecución) |
| `tools/pbi_log.py` | Exporta conversaciones a JSONL incremental |
| `logs/` | Archivos de log diarios (`conversations_YYYY-MM-DD.jsonl`) |

### Modelo semántico

Ubicación en disco:
```
C:\Users\rmib2\OneDrive - lafar.net\manuel.illanes\pbi-demo-chat\AdventureWorks Sales.SemanticModel
```
Debe estar abierto en Power BI Desktop para que el MCP pueda conectarse.

## System prompt del bot

El system prompt incluye: rol, esquema completo del modelo (tablas, columnas, medidas), reglas DAX de eficiencia, e instrucción para invocar la skill `pbi-adventureworks-dax` en consultas complejas.

Configurado en OpenClaw en:
`channels.telegram.accounts.pbi.direct.1353028892.systemPrompt`

### Optimizaciones de costo activas
- **Esquema embebido**: el modelo conoce todas las tablas, columnas y medidas — no necesita explorar el modelo antes de cada query
- **Skill DAX**: `pbi-adventureworks-dax` guía al modelo a escribir DAX correcto en el primer intento
- **Modelo eficiente**: `gpt-5.4-nano` en vez de `gpt-5.6-luna`
- **Reset diario**: sesión reseteada a medianoche (`America/La_Paz`) via automatización OpenClaw (`d4baf3fd`)

## Logging

`tools/pbi_log.py` exporta conversaciones nuevas al archivo de log del día:

```
logs/conversations_2026-09-30.jsonl
```

Cada línea es un JSON con:

```json
{
  "asst_seq": 24,
  "ts": "2026-09-30T20:37:10Z",
  "model": "gpt-5.4-nano",
  "question": "cuantas categorias de productos hay?",
  "answer": "Hay **4 categorías de productos**.",
  "thinking": ["**Investigating MCP Power BI tools**"],
  "tokens": {
    "input": 20330,
    "output": 751,
    "cache_read": 84736,
    "reasoning": 252,
    "total": 105817
  },
  "cost_usd": 0.1665
}
```

El script corre automáticamente **cada minuto** via una automatización de OpenClaw (`PBI_Bot_Logger`, id: `6071e681`). Lee directamente el SQLite de OpenClaw sin overhead de exportación.

Para ejecutarlo manualmente:

```bash
python tools/pbi_log.py
```

## Configuración requerida

- OpenClaw instalado y corriendo con el canal Telegram `pbi` configurado.
- Token del bot en `env.vars.PBI_TELEGRAM_BOT_TOKEN` (config de OpenClaw).
- Plugin `powerbi-modeling` habilitado en OpenClaw.
- Power BI Desktop abierto con el modelo AdventureWorks Sales.
