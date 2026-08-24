# ADR-004 — Gestión de secretos

```meta
Estado:   Aceptada
Fecha:    2026-08-24
Contexto: Inception v3.0 §7 riesgo 7
```

## Contexto

Moon-Jules maneja dos credenciales: la API key de Jules y, si usa la API
REST de GitHub, un PAT. El Inception v2.0 tenía una contradicción: pedía
un `config.toml` "versionable como dotfile" y a la vez temía commitear
la key. Ambas cosas no pueden ser ciertas.

El riesgo dejó de ser hipotético: durante el Spike 01 la key viajó por
un chat y hubo que rotarla.

## Decisión

**La configuración referencia la credencial; nunca la contiene.**

```toml
[jules]
api_key = "env:JULES_API_KEY"     # o "keychain:moon-jules/jules"
```

Resolvedores soportados: `env:VAR` y, en macOS, `keychain:servicio/cuenta`
vía `security find-generic-password`. Un valor literal que no lleve
prefijo de resolvedor es un **error de arranque**, no un aviso. El
`config.toml` queda así versionable de verdad.

Tres medidas más, todas desde el primer commit:

1. **Filtro de redacción en el logger.** Cualquier cadena que contenga
   el valor de una credencial resuelta se sustituye por `«redactado»`
   antes de escribir. Se aplica también a las URLs y a los volcados de
   error del cliente HTTP.
2. **La credencial nunca se acepta por argumento de CLI.** Los
   argumentos quedan en el historial del shell y en `ps`.
3. **`.gitignore` incluye `*.db`, `logs/`, `.env` y `config.toml`
   local**; el repo lleva `config.example.toml`.

## Consecuencias

Un paso extra de setup: el arquitecto debe exportar la variable o
guardar la key en el llavero. A cambio, no existe un camino por el que
la credencial acabe en git.

## Alternativas descartadas

**Key en el TOML con permisos 600.** Protege del vecino, no del `git
add -A`, que es el modo de fallo real.

**Gestor de secretos externo** (Vault, cloud). Contradice el NO 4.
