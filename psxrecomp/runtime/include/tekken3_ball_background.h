#ifndef TEKKEN3_BALL_BACKGROUND_H
#define TEKKEN3_BALL_BACKGROUND_H
#include <stdint.h>
#include <stddef.h>

/* Tekken Ball's beach panorama (fight overlay 800B5A48) is a map of 32px
 * cells: rows of T3_BALL_ROW_CELLS sprites starting at -(scroll mod 32). */
enum { T3_BALL_ROW_CELLS = 15, T3_BALL_MAX_COLUMNS = 64, T3_BALL_MAX_ROWS = 16 };
typedef struct Tekken3BallCell { uint16_t tile, clut; } Tekken3BallCell;
typedef struct Tekken3BallReveal { int x, y; Tekken3BallCell cell; } Tekken3BallReveal;

/* `row` holds the drawn cells of one row, left to right, starting at x0.
 * Locate them in the original map and return the cells missing from the
 * [-margin, 368 + margin) view. A row that matches nowhere, or several
 * places that disagree on the missing cells, reveals nothing. */
size_t tekken3_ball_reveal(const Tekken3BallCell *map, int columns, int rows,
    const Tekken3BallCell row[T3_BALL_ROW_CELLS], int x0, int y, int margin,
    Tekken3BallReveal *out, size_t capacity);
#endif
