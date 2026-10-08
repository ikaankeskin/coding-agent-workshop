"""A simple terminal Snake game using curses.

Controls: arrow keys or WASD to move, P to pause, Q to quit.
Run: python3 snake.py
"""
import curses
import random
import time

HEIGHT, WIDTH = 20, 40

UP, DOWN, LEFT, RIGHT = (-1, 0), (1, 0), (0, -1), (0, 1)

KEYS = {
    curses.KEY_UP: UP, ord("w"): UP, ord("W"): UP,
    curses.KEY_DOWN: DOWN, ord("s"): DOWN, ord("S"): DOWN,
    curses.KEY_LEFT: LEFT, ord("a"): LEFT, ord("A"): LEFT,
    curses.KEY_RIGHT: RIGHT, ord("d"): RIGHT, ord("D"): RIGHT,
}


class Game:
    """Pure game rules; no curses, so it can be tested directly."""

    def __init__(self, height=HEIGHT, width=WIDTH, rng=None):
        self.height, self.width = height, width
        self.rng = rng or random.Random()
        self.snake = [(height // 2, width // 2 - i) for i in range(3)]  # head first
        self.direction = RIGHT
        self.pending = RIGHT  # direction requested for the next tick
        self.score = 0
        self.over = False
        self.won = False
        self.food = self.place_food()

    def place_food(self):
        occupied = set(self.snake)
        free = [(y, x) for y in range(1, self.height - 1)
                for x in range(1, self.width - 1) if (y, x) not in occupied]
        return self.rng.choice(free) if free else None

    def turn(self, new):
        # Compare with the direction actually travelled, so two quick key
        # presses within one tick can't reverse the snake into itself.
        if (new[0] + self.direction[0], new[1] + self.direction[1]) != (0, 0):
            self.pending = new

    def step(self):
        if self.over:
            return
        self.direction = self.pending
        head = (self.snake[0][0] + self.direction[0],
                self.snake[0][1] + self.direction[1])

        grows = head == self.food
        body = self.snake if grows else self.snake[:-1]  # tail moves away
        hit_wall = not (0 < head[0] < self.height - 1 and 0 < head[1] < self.width - 1)
        if hit_wall or head in body:
            self.over = True
            return

        self.snake.insert(0, head)
        if grows:
            self.score += 1
            self.food = self.place_food()
            if self.food is None:
                self.over = self.won = True
        else:
            self.snake.pop()

    @property
    def delay(self):
        """Seconds per tick; speeds up as the score rises."""
        return max(0.05, 0.12 - 0.003 * self.score)


def draw(win, game, paused):
    win.erase()
    win.border()
    win.addstr(0, 2, f" Score: {game.score} ")
    if paused:
        win.addstr(game.height - 1, 2, " PAUSED ")
    if game.food:
        win.addch(game.food[0], game.food[1], "*")
    for i, (y, x) in enumerate(game.snake):
        win.addch(y, x, "@" if i == 0 else "o")
    win.refresh()


def play(stdscr):
    curses.curs_set(0)
    rows, cols = stdscr.getmaxyx()
    if rows < HEIGHT or cols < WIDTH:
        raise SystemExit(f"Terminal too small: need {WIDTH}x{HEIGHT}, have {cols}x{rows}.")

    win = curses.newwin(HEIGHT, WIDTH, 0, 0)
    win.keypad(True)
    game = Game()
    paused = False
    draw(win, game, paused)

    next_tick = time.monotonic() + game.delay
    while not game.over:
        # Wait only until the next tick, so keypresses don't speed up the game.
        remaining = max(0, next_tick - time.monotonic())
        win.timeout(int(remaining * 1000))
        key = win.getch()

        if key in (ord("q"), ord("Q")):
            break
        if key in (ord("p"), ord("P")):
            paused = not paused
            if not paused:
                next_tick = time.monotonic() + game.delay
            draw(win, game, paused)
        elif key in KEYS and not paused:
            game.turn(KEYS[key])

        if not paused and time.monotonic() >= next_tick:
            game.step()
            next_tick += game.delay
            if not game.over:
                draw(win, game, paused)
    return game


def main():
    game = curses.wrapper(play)
    if game.won:
        print(f"You win! Final score: {game.score}")
    else:
        print(f"Game over! Final score: {game.score}")


if __name__ == "__main__":
    main()
