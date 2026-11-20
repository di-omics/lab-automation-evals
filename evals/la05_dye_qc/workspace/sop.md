# Pipetting head check, photometric (excerpt)

1. The head dispenses 50 uL of tartrazine working solution into every well of a clear 96-well plate, one column per
   pass. Each well is topped up with 150 uL of buffer, mixed, and read at 450 nm.
2. A standard curve of the same working solution is pipetted by hand with a calibrated pipette into the same plate
   type, topped up with 150 uL of buffer like the head wells, mixed, and read on the same reader. The 0 uL standard
   is the blank.
3. Convert absorbance to delivered volume with a straight-line fit of absorbance against volume over the whole
   standard curve.
4. Acceptance, per channel at 50 uL: the channel's mean delivered volume is within +/-5% of 50 uL (systematic error),
   and its coefficient of variation (sample standard deviation / mean) is at most 3% (random error).
5. The head is released for the day only if every channel passes. Otherwise it is held for service.
