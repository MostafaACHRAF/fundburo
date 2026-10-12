--create database find_n_lost;

create table app_user (
  id bigserial primary key,
  username text not null,
  email text not null unique,
  role text not null check (role in ('reporter','claimer')),
  created_at timestamptz not null default now()
);

create table item (
  id bigserial primary key,
  user_id bigint not null references app_user(id) on delete cascade,
  item_type text not null check (item_type in ('lost','found')),
  description text not null,
  color text,
  size text,
  usage text,
  address_text text,
  lat double precision,
  lng double precision,
  event_time timestamptz,
  feel text,
  smell text,
  model text,
  image_url text,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '10 days'),
  status text not null default 'active' check (status in ('active','matched','expired'))
);

create table item_match (
  id bigserial primary key,
  lost_item_id bigint not null references item(id) on delete cascade,
  found_item_id bigint not null references item(id) on delete cascade,
  score numeric(5,4) not null check (score >= 0 and score <= 1),
  confidence text not null check (confidence in ('high','medium','low')),
  created_at timestamptz not null default now(),
  unique (lost_item_id, found_item_id)
);
