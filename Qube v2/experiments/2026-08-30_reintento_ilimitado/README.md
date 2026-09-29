# Reintento ilimitado del swing-up (v1.66.0)

**Pregunta:** ¿puede el modo 5 terminar en modo 0 sin que nadie lo haya pedido?

No es una campaña de tasa de éxito ni un barrido de parámetros. Es una pregunta de
máquina de estados, y la respuesta tiene que poder ser «no» de forma verificable.

## Cómo correrlo

```
python validar_reintento.py [minutos]      # def. 5
```

Hace homing si hace falta, pide `m5` y registra `/state` a 5 Hz en `data/`. Al terminar
deja el banco en modo 0.

## Qué cuenta como falla

El script no declara «validado» a menos que se rompa ninguna de estas tres:

1. `mode` cae a 0 sin que el script haya mandado el comando → el modo se perdió solo.
2. `swing_retry_max >= 0` en cualquier muestra → quedó un presupuesto finito.
3. Cero intentos fallidos en toda la tanda → la tanda no ejercitó el reintento y **no
   prueba nada**, aunque no haya caído a 0.

La única salida a modo 0 que se acepta es `swing_fail_reason = 5` (recentrado calado):
esa falla es mecánica y detener el banco es lo correcto.

`autoprueba()` corre el criterio contra tres trazas sintéticas que **deben** fallar y
una que debe pasar, antes de tocar la placa. Sin eso, un criterio que devuelve OK pase
lo que pase se ve igual que uno correcto.

## Resultado del 2026-08-30 (`data/reintento_20260830_230730.jsonl`)

300 s, 1142 muestras, defaults de fábrica (`tn=155`, `sp=60`, `ke=0,65`).

| | |
|---|---|
| Reintentos | **24** |
| Modos vistos en toda la traza | **4 y 5** — ningún 0 |
| Ciclo intento→intento | 11,4 s mediana (8,6 – 18,9) |
| Traspasos a m4 | 20 de 24 intentos |
| Supervivencia en m4 | 0,79 s mediana · 1,76 s máx · ninguno llegó a 3 s |
| Fallas | 62 % brazo al tope · 33 % vuelta del péndulo · 4 % caída |
| Reparto del tiempo | 54 % esperando quietud · 35 % bombeando · 6 % m4 · 6 % recentrando |

Con el firmware anterior (`swing_retry_max = 3`) la tanda habría terminado en el
reintento 3, a los 42 s.

Las filas de abajo de la tabla son observaciones, no el resultado: describen al
swing-up, que no es lo que esta tanda estaba midiendo. Sirven como línea base para
cualquier ajuste posterior, y por eso corrió sin tocar un solo parámetro.
