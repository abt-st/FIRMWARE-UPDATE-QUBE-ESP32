# Tandas con el firmware v1.67.0 — ANTES de corregir P26

Estas seis tandas se midieron con los seis términos de «empujar al centro» sin cruzar el
signo del motor, o sea empujando **hacia el tope** (ver `CHANGELOG.md`, v1.68.0).

**No son comparables con las tandas de v1.68.0**, y ninguna sintonía sacada de acá es
transferible. Se conservan porque son la evidencia que motivó la corrección:

| tanda | traspasos | p50 | max | veredicto |
|---|---|---|---|---|
| `C0_base` #1 | 8 | 530 ms | 799 ms | línea base |
| `C0_base` #2 | 14 | 753 ms | 1174 ms | línea base |
| `C1_pc1` | 19 | 606 ms | 1217 ms | dentro del ruido |
| `C3_lc0` | 13 | 246 ms | 290 ms | no sirve |
| `C5_lpm110` | 15 | 417 ms | 1226 ms | no sirve |
| `C9_lc600` | 11 | 447 ms | 1502 ms | no sirve |

Lo que dejan establecido, y sigue valiendo:

1. **La banda de ruido de una tanda de 5 minutos es enorme.** Dos corridas de `C0_base`
   con parámetros idénticos dieron 8 y 14 traspasos, p50 530 y 753 ms. Cualquier
   criterio que compare contra una sola base declara «mejora» a la mitad de las
   repeticiones de la propia base.
2. **`lc=0` es lo único que salió claramente fuera de esa banda**, y para el lado malo:
   nueve caídas del péndulo contra una. El catch hace trabajo útil; P4/H2 queda
   refutada en su forma extrema.
3. **23 de 28 intentos murieron en el tope del brazo y ninguno con el péndulo caído.**
   Es lo que P26 predice, y es la evidencia que cerró el argumento.
