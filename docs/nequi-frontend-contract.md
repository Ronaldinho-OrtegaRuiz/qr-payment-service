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

### Asignar droguería

`PATCH /nequi-payments/{id}`

```json
{ "drogueria_id": 1 }
```

Quitar asignación:
```json
{ "drogueria_id": null }
```

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

### Stats
Tabla aparte de QR. En stats del front: agrupar por `drogueria_id` (y bucket “sin asignar” si quieren). La lista operativa es **una sola tabla**.
