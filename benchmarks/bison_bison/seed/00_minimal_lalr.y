%token NUM
%start input
%%
input:
    /* empty */
  | input line
  ;
line:
    '\n'
  | expr '\n'
  ;
expr:
    NUM
  | expr '+' expr
  ;
%%
