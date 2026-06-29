# silly-cat 🐱

A silly cat that plays in your terminal — as a **native program that lives on the machine**.
One C89 source file, the whole animation embedded, no interpreter, no browser, no network.

```
            ++    ++.
           :   .--=-  *   -#::-
           :  --+-     +-     :
           :                 -
           : :.-*   :#.=    =.
           +:-.%+   = .%:   :-
          .-   ..      +    +=            *
            *   .*.+        :=       ==.  *=
            .%-.       =*=          .+ +  .+
           :*-:+        :+          *   .* :
        #-   .=*- -=    +         ==       -
       *    +* + *       =  +**+           *
         .      =    #    +:              *
              *+   --      *            .*
            .==: .  .-     :         .*=
              *     + *     :-*:    -%
                -   + .+    +
                -   +  :    *
                -   *   -   :=
                +   :    :**:
```

## Run it

**Just want the binary?** Download it, no code needed:

→ **[Download `meow` (macOS, Apple Silicon)](https://github.com/arian-shamaei/silly-catui/releases/latest/download/meow-macos-arm64)**

```sh
chmod +x meow-macos-arm64
xattr -d com.apple.quarantine meow-macos-arm64   # macOS: clear the download flag
./meow-macos-arm64
```

**Build from source** (any platform with a C compiler):

```sh
cc -O2 -o meow c/meow.c    # gcc, clang, tcc, or MSVC: cl c\meow.c
./meow                     # Ctrl-C to quit
```

### Options

```
./meow                fill the terminal, loop forever
./meow 120 40         force WIDTH x HEIGHT in characters
./meow --loops 3      play 3 times then exit
./meow --scroll       no cursor control — for teletypes / dumb terminals
```

## What's in here

| file | what |
|------|------|
| `c/meow.c` | the entire program — C89, standard library only |
| `c/meow_frames.h` | the animation, embedded (RLE-compressed) so there are no external assets |
| `silly-cat.gif` | the original cat the frames came from |

## Reach

C compilers exist for very nearly every architecture from the 1970s to today, so this
runs natively on an enormous range of machines — anything with a C compiler and a text
display. (Not *literally* every computer ever built: there's no single artifact that runs
on machines with no shared instruction set, compiler, or screen — but this gets remarkably
close.)
