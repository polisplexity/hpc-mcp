/* Fixed-work, double-precision heat diffusion with periodic MPI halos. */

#define _GNU_SOURCE
#include <math.h>
#include <mpi.h>
#include <openssl/sha.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>

static const double alpha = 0.2;

static void fail(const char *message)
{
    fprintf(stderr, "%s\n", message);
    MPI_Abort(MPI_COMM_WORLD, 1);
    exit(1);
}

static void *allocate(size_t count, size_t size)
{
    void *data = calloc(count, size);
    if (data == NULL)
        fail("Could not allocate the stencil workspace");
    return data;
}

static void advance(double *current, double *next, int local_rows, int cols, int rank, int ranks)
{
    const size_t stride = (size_t)cols + 2;
    const int above = (rank + ranks - 1) % ranks;
    const int below = (rank + 1) % ranks;
    MPI_Sendrecv(current + stride + 1, cols, MPI_DOUBLE, above, 0,
                 current + (local_rows + 1) * stride + 1, cols, MPI_DOUBLE, below, 0,
                 MPI_COMM_WORLD, MPI_STATUS_IGNORE);
    MPI_Sendrecv(current + local_rows * stride + 1, cols, MPI_DOUBLE, below, 1,
                 current + 1, cols, MPI_DOUBLE, above, 1,
                 MPI_COMM_WORLD, MPI_STATUS_IGNORE);
    for (int row = 1; row <= local_rows; row++) {
        double *middle = current + row * stride;
        const double *north = middle - stride;
        const double *south = middle + stride;
        middle[0] = middle[cols];
        middle[cols + 1] = middle[1];
        for (int col = 1; col <= cols; col++) {
            double adjacent = north[col] + south[col] + middle[col - 1] + middle[col + 1];
            next[row * stride + col] = middle[col] + alpha * (adjacent - 4.0 * middle[col]);
        }
    }
}

static double decay(int rows, int cols, int row_mode, int col_mode, int steps)
{
    double row_sine = sin(M_PI * row_mode / rows);
    double col_sine = sin(M_PI * col_mode / cols);
    return pow(1.0 - 4.0 * alpha * (row_sine * row_sine + col_sine * col_sine), steps);
}

int main(int argc, char **argv)
{
    MPI_Init(&argc, &argv);
    int rank, ranks;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &ranks);
    if (argc != 4 + ranks || ranks > 4)
        fail("Expected grid rows, columns, steps and one CPU per rank");
    const int rows = atoi(argv[1]), cols = atoi(argv[2]), steps = atoi(argv[3]);
    if (rows < 32 || cols < 32 || steps < 1 || rows % ranks != 0)
        fail("The grid must split equally across MPI ranks");
    const int cpu = atoi(argv[4 + rank]);
    if (cpu < 0 || cpu >= CPU_SETSIZE)
        fail("CPU index exceeds the affinity mask");
    cpu_set_t affinity;
    CPU_ZERO(&affinity);
    CPU_SET(cpu, &affinity);
    if (sched_setaffinity(0, sizeof affinity, &affinity) != 0 || sched_getcpu() != cpu)
        fail("Could not pin the MPI rank to its allocated CPU");

    const int local_rows = rows / ranks;
    const size_t stride = (size_t)cols + 2;
    double *current = allocate((local_rows + 2) * stride, sizeof *current);
    double *next = allocate((local_rows + 2) * stride, sizeof *next);
    double *col_a = allocate(cols, sizeof *col_a);
    double *col_b = allocate(cols, sizeof *col_b);
    for (int col = 0; col < cols; col++) {
        col_a[col] = cos(2.0 * M_PI * 11 * col / cols);
        col_b[col] = sin(2.0 * M_PI * 23 * col / cols);
    }
    for (int row = 1; row <= local_rows; row++) {
        int global = rank * local_rows + row - 1;
        double a = 0.3 * cos(2.0 * M_PI * 17 * global / rows);
        double b = 0.2 * sin(2.0 * M_PI * 31 * global / rows);
        for (int col = 0; col < cols; col++)
            current[row * stride + col + 1] = 0.5 + a * col_a[col] + b * col_b[col];
    }

    MPI_Barrier(MPI_COMM_WORLD);
    double start = MPI_Wtime();
    for (int step = 0; step < steps; step++) {
        advance(current, next, local_rows, cols, rank, ranks);
        double *previous = current;
        current = next;
        next = previous;
    }
    double elapsed = MPI_Wtime() - start;
    double kernel_seconds = 0.0, max_error = 0.0, local_error = 0.0;
    double a_decay = decay(rows, cols, 17, 11, steps);
    double b_decay = decay(rows, cols, 31, 23, steps);
    unsigned char *row_hashes = allocate(local_rows, SHA256_DIGEST_LENGTH);
    for (int row = 1; row <= local_rows; row++) {
        int global = rank * local_rows + row - 1;
        double a = 0.3 * a_decay * cos(2.0 * M_PI * 17 * global / rows);
        double b = 0.2 * b_decay * sin(2.0 * M_PI * 31 * global / rows);
        double *cells = current + row * stride + 1;
        for (int col = 0; col < cols; col++) {
            double expected = 0.5 + a * col_a[col] + b * col_b[col];
            if (!isfinite(cells[col]))
                fail("The stencil produced a non-finite value");
            local_error = fmax(local_error, fabs(cells[col] - expected));
        }
        SHA256((unsigned char *)cells, cols * sizeof *cells, row_hashes + (row - 1) * SHA256_DIGEST_LENGTH);
    }

    unsigned char *ordered = rank == 0 ? allocate(rows, SHA256_DIGEST_LENGTH) : NULL;
    int observed_cpu = sched_getcpu();
    int rank_cpus[4] = {0};
    MPI_Gather(&observed_cpu, 1, MPI_INT, rank_cpus, 1, MPI_INT, 0, MPI_COMM_WORLD);
    MPI_Reduce(&elapsed, &kernel_seconds, 1, MPI_DOUBLE, MPI_MAX, 0, MPI_COMM_WORLD);
    MPI_Reduce(&local_error, &max_error, 1, MPI_DOUBLE, MPI_MAX, 0, MPI_COMM_WORLD);
    MPI_Gather(row_hashes, local_rows * SHA256_DIGEST_LENGTH, MPI_BYTE,
               ordered, local_rows * SHA256_DIGEST_LENGTH, MPI_BYTE, 0, MPI_COMM_WORLD);
    if (rank == 0) {
        unsigned char digest[SHA256_DIGEST_LENGTH];
        SHA256(ordered, rows * SHA256_DIGEST_LENGTH, digest);
        int distinct = ranks;
        for (int i = 0; i < ranks; i++)
            for (int j = 0; j < i; j++)
                if (rank_cpus[i] == rank_cpus[j])
                    distinct = 0;
        printf("{\"ranks\":%d,\"pinned_cpus\":%d,\"kernel_seconds\":%.9f,"
               "\"max_abs_error\":%.17g,\"field_digest\":\"", ranks, distinct, kernel_seconds, max_error);
        for (size_t i = 0; i < sizeof digest; i++)
            printf("%02x", digest[i]);
        puts("\"}");
    }
    free(ordered);
    free(row_hashes);
    free(col_b);
    free(col_a);
    free(next);
    free(current);
    MPI_Finalize();
    return 0;
}
