data {
  int<lower=1> P;
  vector<lower=0, upper=1>[P] x;
  array[P] int<lower=1> N;
  array[P] int<lower=0> Y;
  vector<lower=0>[P] N1_weight;
  vector<lower=0>[P] N2_weight;
  real<lower=0> king_lambda;
}

parameters {
  real<lower=0> c_1;
  real<lower=0> d_1;
  real<lower=0> c_2;
  real<lower=0> d_2;
  vector<lower=0, upper=1>[P] b_1;
  vector<lower=0, upper=1>[P] b_2;
}

model {
  vector[P] theta = x .* b_1 + (1 - x) .* b_2;

  // Exact PyEI pyei.two_by_two.ei_beta_binom_model hierarchy.
  c_1 ~ exponential(king_lambda);
  d_1 ~ exponential(king_lambda);
  c_2 ~ exponential(king_lambda);
  d_2 ~ exponential(king_lambda);
  b_1 ~ beta(c_1, d_1);
  b_2 ~ beta(c_2, d_2);
  Y ~ binomial(N, theta);
}

generated quantities {
  real beta1_aggregate = dot_product(N1_weight, b_1) / sum(N1_weight);
  real beta2_aggregate = dot_product(N2_weight, b_2) / sum(N2_weight);
  real contrast_aggregate = beta1_aggregate - beta2_aggregate;
}
