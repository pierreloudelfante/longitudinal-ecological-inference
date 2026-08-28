data {
  int<lower=1> I;
  array[I] int<lower=1> N_g;
  array[I] int<lower=0> Y;
  vector<lower=0, upper=1>[I] X;
  real<lower=0> king_lambda;
}

parameters {
  real<lower=0> c_1;
  real<lower=0> d_1;
  real<lower=0> c_2;
  real<lower=0> d_2;
  vector<lower=0, upper=1>[I] b_1;
  vector<lower=0, upper=1>[I] b_2;
}

transformed parameters {
  vector<lower=0, upper=1>[I] theta = X .* b_1 + (1 - X) .* b_2;
}

model {
  c_1 ~ exponential(king_lambda);
  d_1 ~ exponential(king_lambda);
  c_2 ~ exponential(king_lambda);
  d_2 ~ exponential(king_lambda);
  b_1 ~ beta(c_1, d_1);
  b_2 ~ beta(c_2, d_2);
  Y ~ binomial(N_g, theta);
}
