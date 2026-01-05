#!/bin/bash

BASE_URL="http://localhost:8080"

CALC_URL="${BASE_URL}/calc"
RELOAD_URL="${BASE_URL}/admin/reload"

echo "===== TEST START (PARALLEL MODE) ====="

JSON1='{
  "A": { "input":[ { "cell":"Sheet1!A1","value":"1" } ], "output":[ "Sheet1!A1:A100" ] },
  "S": { "input":[ { "cell":"Sheet1!A1","value":"1" } ], "output":[ "Sheet1!A1:A100" ] }
}'

JSON2='{
  "S": { "input":[ { "cell":"Sheet1!A1","value":"1" } ], "output":[ "Sheet1!A1:A100" ] }
}'

LOG_FILE="./test_results.tmp"
rm -f "$LOG_FILE"


###############################################
# 함수: 병렬 calc 실행 (성공 여부, 초 단위 시간 기록)
###############################################
run_parallel_calc() {
    local COUNT=$1
    echo "→ Running $COUNT parallel calc requests..."

    for i in $(seq 1 $COUNT); do
        if (( i % 2 == 0 )); then DATA="$JSON2"; NAME="JSON2"; else DATA="$JSON1"; NAME="JSON1"; fi

        (
            start_time=$(date +%s.%3N)
            echo "${i} 시작"

            # 응답 본문은 버리고 HTTP code만 받음
            http_code=$(curl -s -o /dev/null -w "%{http_code}" \
                -X POST "$CALC_URL" \
                -H "Content-Type: application/json" \
                -d "$DATA")

            end_time=$(date +%s.%3N)

            # 소수 2자리까지 초 단위로 변환
            elapsed=$(echo "$end_time - $start_time" | bc -l)
            elapsed_fmt=$(printf "%.2f" "$elapsed")

            status="OK"
            if [[ "$http_code" != "200" ]]; then
                status="FAIL($http_code)"
            fi

            echo "${i} 종료"
            echo "[CALC][$i] ${elapsed_fmt}s ${status} (${NAME})" >> "$LOG_FILE"
        ) &
    done

    wait
}


# ###############################################
# # STEP 1: /calc 5개 병렬
# ###############################################
# echo "===== STEP 1: 5 parallel calc ====="
# run_parallel_calc 5


# ###############################################
# # STEP 2: reload 호출
# ###############################################
# echo "===== STEP 2: Trigger reload ====="

# start_time=$(date +%s.%3N)

# reload_code=$(curl -s -o /dev/null -w "%{http_code}" \
#     -X POST "$RELOAD_URL" \
#     -H "Content-Type: application/json" \
#     -d '{}')

# end_time=$(date +%s.%3N)
# elapsed=$(echo "$end_time - $start_time" | bc -l)
# elapsed_fmt=$(printf "%.2f" "$elapsed")

# reload_status="OK"
# if [[ "$reload_code" != "200" ]]; then
#     reload_status="FAIL($reload_code)"
# fi

# echo "[RELOAD] ${elapsed_fmt}s ${reload_status}" | tee -a "$LOG_FILE"


###############################################
# STEP 3: /calc 20개 병렬
###############################################
echo "===== STEP 3: 20 parallel calc ====="
run_parallel_calc 20


###############################################
# RESULT
###############################################
echo "===== TEST COMPLETE ====="

avg=$(awk '{ sum += $2 } END { if (NR>0) printf "%.2f", sum/NR; }' "$LOG_FILE")
echo "Avg time per calc: ${avg}s"

echo "---- Raw results ----"
cat "$LOG_FILE"
