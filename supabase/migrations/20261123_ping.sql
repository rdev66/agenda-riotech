-- Keep-alive: evita pause do projeto free por inatividade.
create or replace function public.ping() returns int language sql stable as 'select 1';
grant execute on function public.ping() to anon;
