args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 2)
orders <- read.csv(args[[1]], colClasses = c("character", "integer", "integer"))
orders$revenue_cents <- orders$units * orders$unit_price_cents
by_region <- aggregate(cbind(units, revenue_cents) ~ region, data = orders, FUN = sum)
by_region <- by_region[order(by_region$region), ]
stopifnot(all(grepl("^[a-z]+$", by_region$region)))

entries <- sprintf('"%s":{"units":%d,"revenue_cents":%d}',
                   by_region$region, by_region$units, by_region$revenue_cents)
summary <- sprintf('{"r_version":"%s","rows":%d,"total_revenue_cents":%d,"regions":{%s}}',
                   as.character(getRversion()), nrow(orders), sum(orders$revenue_cents), paste(entries, collapse = ","))
writeLines(summary, args[[2]])
