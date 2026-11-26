/* Nondestructive boot registration. No application/data/cache removal. */
#include "mini.h"

int main(int argc, char **argv, char **envp)
{
    (void)argc; (void)argv; (void)envp;
    struct stat st;
    const char *app = "/private/preboot/apps/Iris.app";
    const char *log = "/private/var/mobile/Library/Logs/hakios-iris-registration.log";
    mkdir("/private/var/mobile/Library/Logs", 0755);
    chown("/private/var/mobile/Library/Logs", 501, 501);
    int fd = open(log, O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (fd >= 0) { dup2(fd, 1); dup2(fd, 2); close(fd); }
    printf("Iris boot registration: preserve existing data\n");
    if (stat(app, &st) != 0 || stat("/redwood/bin/uicache", &st) != 0) {
        printf("Iris app or uicache unavailable: %s\n", strerror(errno));
        return 1;
    }
    for (int attempt = 1; attempt <= 20; attempt++) {
        usleep(3000000);
        char *args[] = { "/redwood/bin/uicache", "-p", (char *)app, NULL };
        char *env[] = { "PATH=/redwood/bin:/usr/bin:/bin", "HOME=/var/mobile", NULL };
        pid_t pid = fork();
        if (pid == 0) { execve(args[0], args, env); _exit(127); }
        int status = 0;
        int reaped = pid > 0 && wait4(pid, &status, 0, NULL) == pid;
        printf("Iris uicache attempt %d: reaped=%d status=%d\n", attempt, reaped, status);
        if (reaped && WIFEXITED(status) && WEXITSTATUS(status) == 0) {
            printf("Registration utility exited successfully; icon needs screen confirmation\n");
            return 0;
        }
    }
    printf("Iris registration failed after 20 attempts\n");
    return 1;
}
