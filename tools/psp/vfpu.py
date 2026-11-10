#!/usr/bin/env python3
"""sin, cos et asin de la VFPU de la PSP, approches avec math (pas de table ni de code tiers).

Unites de la VFPU : vsin / vcos / vrot prennent un angle en quarts de tour (x * pi / 2), vasin rend
asin(x) / (pi / 2). Calcul en double, arrondi en float32. Le materiel calcule ces fonctions par un
interpolateur a 128 segments : les resultats different au dernier bit pres pour sin / cos (ecart
absolu <= 5e-7) et davantage pour asin pres de |x| = 1 (<= 1e-3 pour |x| < 0,99, ~0,02 au-dela :
l'asin du materiel est grossier sur son dernier segment). Mesure du 2026-10-25 (TIPS 49 sexies).
"""
import math
import numpy as np


def vfpu_sin(x):
    """sin(x * pi / 2) (vsin, vrot)."""
    return np.float32(math.sin(float(x) * (math.pi / 2)))


def vfpu_cos(x):
    """cos(x * pi / 2) (vcos, vrot)."""
    return np.float32(math.cos(float(x) * (math.pi / 2)))


def vfpu_asin(x):
    """asin(x) / (pi / 2) (vasin) ; NaN hors de [-1, 1] comme le materiel."""
    x = float(x)
    if abs(x) > 1: return np.float32(math.copysign(math.nan, x))
    return np.float32(math.asin(x) / (math.pi / 2))
