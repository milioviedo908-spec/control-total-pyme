# Control Total PyME

App web de gestión para PyMEs: contabilidad, stock, facturación de mostrador y CapTable de socios.

## Stack
- **Frontend:** HTML5 + CSS3 + JavaScript (Chart.js vía CDN para el gráfico del dashboard)
- **Backend:** Python (Flask)
- **Base de datos:** PostgreSQL (pensada para [Neon](https://neon.tech))

> Nota: `app_sqlite_backup.py`, `schema_sqlite_backup.sql` y `requirements_sqlite_backup.txt` son la versión original con SQLite (100% local, sin depender de internet). El proyecto activo (`app.py`, `schema.sql`, `requirements.txt`) usa PostgreSQL/Neon para poder desplegarse en Render, Railway, etc.

## Deploy con GitHub + Neon + Render

1. **Neon** (base de datos):
   - Creá una cuenta en https://neon.tech y un proyecto nuevo.
   - Copiá el "Connection string" (empieza con `postgresql://...`).

2. **GitHub**:
   - Subí esta carpeta a un repositorio nuevo.

3. **Render** (hosting):
   - Creá un "Web Service" nuevo y conectalo a tu repo de GitHub (Render detecta el `render.yaml` automáticamente, o configurá a mano: Build Command `pip install -r requirements.txt`, Start Command `gunicorn app:app`).
   - En "Environment", agregá la variable `DATABASE_URL` con el connection string de Neon.
   - Al desplegar, la primera vez que la app arranca crea las tablas solas (`init_db()`), con los datos de ejemplo.

## Desarrollo local (contra Neon)

1. Instalar dependencias:
   ```
   pip install -r requirements.txt
   ```

2. Copiar `.env.example` a `.env` y completar `DATABASE_URL` con tu cadena de Neon (y cargar las variables, por ejemplo con `python-dotenv` o exportándolas en la terminal).

3. Ejecutar la aplicación:
   ```
   python app.py
   ```

4. Abrir en el navegador:
   ```
   http://localhost:5000
   ```

## Accesos de prueba

- **Modo Mostrador (rol público):** PIN `1234`
  - Puede: registrar ventas, imprimir tickets, consultar stock.
  - No ve: caja, deudas, socios ni reportes gerenciales.

- **Modo Administrador (rol privado):**
  - Email: `admin@pyme.com`
  - Contraseña: `admin123`
  - Acceso completo: dashboard, finanzas, flujo de caja, costos, stock, socios, historial y cierres mensuales.

⚠️ Cambiá el PIN, el usuario admin y la `secret_key` de `app.py` antes de usarlo en producción.

## Estructura del proyecto

```
control_total_pyme/
├── app.py                  # Backend Flask (rutas, lógica, auth)
├── schema.sql               # Esquema de la base de datos
├── requirements.txt
├── static/
│   ├── css/style.css        # Estética azul institucional / celeste / off-white
│   └── js/main.js
└── templates/
    ├── base.html             # Layout: sidebar + header
    ├── acceso.html            # Selección de modo de acceso
    ├── acceso_pin.html
    ├── acceso_admin.html
    ├── dashboard.html
    ├── mostrador.html
    ├── ticket.html
    ├── stock.html
    ├── flujo_caja.html
    ├── finanzas.html
    ├── costos.html
    ├── socios.html
    ├── historial.html
    └── cierre_mensual.html
```

## Módulos implementados (según el documento técnico)

- ✅ Dashboard ejecutivo (ventas semana, producto top, ticket promedio, caja disponible + gráfico)
- ✅ Facturación de mostrador con descuento automático de stock e impresión de ticket
- ✅ Estructura financiera: activos, pasivos y patrimonio neto
- ✅ Flujo de caja diario (ingresos/egresos categorizados)
- ✅ Costos fijos/variables y cálculo de punto de equilibrio
- ✅ Control de stock con alertas de mínimo y valorización total
- ✅ Socios (CapTable) con distribución automática de utilidades
- ✅ Roles diferenciados: público (PIN) y privado (email + contraseña con hash)
- ✅ Historial de movimientos (auditoría con fecha, usuario y monto)
- ✅ Cierre mensual con guardado de informes históricos

## Posibles próximos pasos
- Migrar a PostgreSQL para producción/escalabilidad.
- Agregar impresión térmica real (integración con driver de impresora).
- Exportar informes de cierre a PDF/Excel.
- Panel de edición de precios/costos por lote.
