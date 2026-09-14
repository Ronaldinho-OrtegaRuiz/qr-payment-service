## Nequi capture — contrato frontend

Base: `https://sistema-validacion-pagos-qr-production.up.railway.app`  
Auth front: `Authorization: Bearer <token>` (mismo `/login` de siempre).  
La app del teléfono usa `X-Nequi-Device-Key` solo en ingest (no lo usa el front).

### Lista unificada (sin tabs Ricky/Yessi)

`GET /nequi-payments?page=1&page_size=20&assigned=all`

Query opcional:
- `assigned=all|true|false` — `false` = sin droguería
- `drogueria_id=1|2` — solo para stats/filtros, no obligatorio en la vista principal
- `date_from`, `date_to` (`YYYY-MM-DD`)

Respuesta:
```json
{
  "items": [
    {
      "id": 1,
      "client": "RONALDINHO ORTEGA",
      "value": "63.00",
      "notified_at": "2026-09-14T14:15:00-05:00",
      "drogueria_id": null,
      "notification_key": "...",
      "raw_text": "RONALDINHO ORTEGA te envió 63, ¡lo mejor!",
      "device_id": "abc",
      "assigned_at": null,
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "pages": 1
}
```

### Catálogo de droguerías (para el selector)

`GET /droguerias`  
Auth: Bearer

```json
[
  { "id": 1, "name": "Ricky", "shift_count": 2, "schedule_count": 2 },
  { "id": 2, "name": "Yessi", "shift_count": 2, "schedule_count": 2 }
]
```

En el UI: mostrar `name`, al asignar mandar `drogueria_id` = `id`.

### Asignar droguería

`PATCH /nequi-payments/{id}`

```json
{ "drogueria_id": 1 }
```

Quitar asignación:
```json
{ "drogueria_id": null }
```

### Borrar pago Nequi

`DELETE /nequi-payments/{id}`  
Auth: Bearer

Para transferencias personales / que no son de la droguería.

Respuesta `200`:
```json
{ "ok": true, "id": 1 }
```

`404` si no existe.

### Estadísticas Nequi

`GET /stats/nequi?drogueria_id=1&period=month&year=2026&month=9`  
`GET /stats/nequi?drogueria_id=1&period=year&year=2026`

Auth: Bearer. Misma forma de fechas que `/stats` (QR).  
Solo cuenta pagos **ya asignados** a esa droguería (`drogueria_id`). Los sin asignar no entran.

**Mes** (`period=month`):
```json
{
  "period": "month",
  "year": 2026,
  "month": 9,
  "drogueria_id": 1,
  "divisor_days": 14,
  "kpis": {
    "payments_count": 12,
    "total_value": "350000.00",
    "avg_payments_per_day": "0.86",
    "avg_value_per_day": "25000.00",
    "avg_value_per_payment": "29166.67",
    "min_day": { "date": "2026-09-03", "value": "5000.00" },
    "max_day": { "date": "2026-09-10", "value": "80000.00" },
    "days_with_sales": 8,
    "days_empty": 6,
    "unique_clients": 7,
    "vs_previous": { "payments_pct": "10.00", "value_pct": "-5.50" }
  },
  "series": [
    { "date": "2026-09-01", "count": 0, "value": "0.00" },
    { "date": "2026-09-02", "count": 2, "value": "15000.00" }
  ]
}
```

**Año** (`period=year`):
```json
{
  "period": "year",
  "year": 2026,
  "drogueria_id": 1,
  "divisor_months": 9,
  "kpis": {
    "payments_count": 90,
    "total_value": "2100000.00",
    "avg_payments_per_month": "10.00",
    "avg_value_per_month": "233333.33",
    "avg_value_per_payment": "23333.33",
    "best_month": { "month": 3, "value": "400000.00" },
    "worst_month": { "month": 1, "value": "50000.00" },
    "unique_clients": 40,
    "vs_previous": { "payments_pct": null, "value_pct": null }
  },
  "series": [
    { "month": 1, "count": 5, "value": "50000.00" },
    { "month": 2, "count": 8, "value": "120000.00" }
  ]
}
```

Defaults: si omites `year`/`month`, usa fecha actual en `PAYMENTS_TZ`.  
`vs_previous.*.pct` puede ser `null` si el periodo anterior fue 0.

### Ingest (solo app teléfono)

`POST /nequi-payments/ingest`  
Header: `X-Nequi-Device-Key: <secret>`

```json
{
  "items": [
    {
      "client": "RONALDINHO ORTEGA",
      "value": "63.00",
      "notified_at": 1789400000000,
      "notification_key": "0|com.nequi.MobileApp|...",
      "raw_text": "...",
      "device_id": "android-id"
    }
  ]
}
```

Idempotente por `notification_key`.

### Notas UI
- Lista operativa: **una sola tabla** Nequi.
- Stats: endpoint aparte `/stats/nequi` (no mezclado con QR en `/stats`).
- Para que cuenten en stats hay que **asignar** droguería antes.
