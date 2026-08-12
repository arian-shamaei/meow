/*
 * meow_min.c -- the stripped floor.  48x48 x8 frames, 1-bit, ~2.25 KB data.
 *
 * The core (cat_play + render) touches NO libc.  Everything the machine
 * provides comes through two hooks:  cat_putbyte() and cat_delay_ms().
 * Wire them to a UART, a framebuffer, or (here) stdout -- the cat does not
 * care.  This is the freestanding boundary the study describes.
 */
#include "catmin.h"

/* ---- platform hooks: the ONLY machine-specific code -------------------- */
#include <unistd.h>
#include <time.h>
static void cat_putbyte(unsigned char b){ write(1,&b,1); }
static void cat_delay_ms(unsigned ms){
    struct timespec t; t.tv_sec=ms/1000u; t.tv_nsec=(long)(ms%1000u)*1000000L;
    nanosleep(&t,0);
}
/* ----------------------------------------------------------------------- */

static const unsigned char DOT[4][2]={{1,8},{2,16},{4,32},{64,128}};

static int getpx(const unsigned char*f,int y,int x){
    int i=y*CAT_D+x; return (f[i>>3]>>(7-(i&7)))&1;
}
static void puts_(const char*s){ while(*s) cat_putbyte((unsigned char)*s++); }

static void render(const unsigned char*f){
    int cy,cx,dy,dx;
    puts_("\033[H");                    /* cursor home (one escape/frame) */
    for(cy=0;cy<CAT_D/4;cy++){
        for(cx=0;cx<CAT_D/2;cx++){
            int bits=0;
            for(dy=0;dy<4;dy++)for(dx=0;dx<2;dx++)
                if(getpx(f,cy*4+dy,cx*2+dx)) bits|=DOT[dy][dx];
            if(!bits) cat_putbyte(' ');
            else{ cat_putbyte(0xE2); cat_putbyte(0xA0|(bits>>6));
                  cat_putbyte(0x80|(bits&0x3F)); }
        }
        cat_putbyte('\n');
    }
}

static void cat_play(int loops){
    int played=0,f;
    puts_("\033[2J\033[?25l");
    for(;;){
        for(f=0;f<CAT_NF;f++){
            render(cat_bits + f*CAT_BPF);
            cat_delay_ms(cat_ms[f]);
        }
        if(loops>0 && ++played>=loops) break;
    }
    puts_("\033[?25h\n");
}

int main(int argc,char**argv){
    int loops=0,i;
    for(i=1;i<argc;i++){
        if(argv[i][0]=='-'&&argv[i][1]=='-'&&argv[i][2]=='o') loops=1; /* --once */
        else { int n=0,j=0; while(argv[i][j]>='0'&&argv[i][j]<='9') n=n*10+argv[i][j++]-'0'; if(n)loops=n; }
    }
    cat_play(loops);
    return 0;
}
