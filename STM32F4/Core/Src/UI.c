/*
 * UI.c
 *
 *  Serial command protocol: Pi <-> STM32 over USART2 (USB VCP).
 *  Uses a two-phase state machine for RX:
 *    Phase 0 — scan byte-by-byte for START_RX (0xAA)
 *    Phase 1 — receive remaining 18 payload+CRC bytes
 *  This auto-synchronises after USB-VCP enumeration garbage.
 */

#include "UI.h"
#include "display/helper.h"

extern motor_t  *motors[];
extern UART_HandleTypeDef huart2;

/* ── Shared volatile state ──────────────────────────────────────────── */
volatile int32_t  target_steps[4]  = {0, 0, 0, 0};
volatile uint8_t  new_target_flag  = 0;
volatile uint8_t  gripper_cmd      = 0;
volatile uint8_t  reset_request    = 0;
volatile uint8_t  home_request     = 0;
volatile int32_t  home_steps[4]    = {0, 0, 0, 0};
volatile uint8_t  estop_request    = 0;
volatile uint8_t  homing_done_flag = 0;
volatile uint8_t  error_flag       = 0;

uint8_t rx_buf[RX_FRAME_SIZE];

/* RX state machine: 0 = scanning for start byte, 1 = receiving payload */
static volatile uint8_t rx_phase = 0;

/* ── CRC ────────────────────────────────────────────────────────────── */
uint8_t crc8_xor(uint8_t *data, uint8_t len)
{
    uint8_t crc = 0;
    for (uint8_t i = 0; i < len; i++)
        crc ^= data[i];
    return crc;
}

/* ── Helpers ────────────────────────────────────────────────────────── */
static int32_t extract_int32(uint8_t *buf)
{
    int32_t val;
    memcpy(&val, buf, 4);
    return val;
}

static void pack_int32(uint8_t *buf, int32_t val)
{
    memcpy(buf, &val, 4);
}

/* ── Process a validated frame (called from ISR) ────────────────────── */
static void process_frame(void)
{
    cmd_id_t cmd = (cmd_id_t)rx_buf[1];

    switch (cmd)
    {
    case CMD_STREAM_POS:
        target_steps[0] = extract_int32(&rx_buf[2]);
        target_steps[1] = extract_int32(&rx_buf[6]);
        target_steps[2] = extract_int32(&rx_buf[10]);
        target_steps[3] = extract_int32(&rx_buf[14]);
        new_target_flag = 1;
        break;

    case CMD_RESET:
        reset_request = 1;
        break;

    case CMD_HOME:
        home_steps[0] = extract_int32(&rx_buf[2]);
        home_steps[1] = extract_int32(&rx_buf[6]);
        home_steps[2] = extract_int32(&rx_buf[10]);
        home_steps[3] = extract_int32(&rx_buf[14]);
        home_request = 1;
        break;

    case CMD_GRIP_OPEN:
        gripper_cmd = CMD_GRIP_OPEN;
        break;

    case CMD_GRIP_CLOSE:
        gripper_cmd = CMD_GRIP_CLOSE;
        break;

    case CMD_ESTOP:
        estop_request = 1;
        break;

    default:
        break;
    }
}

/* ── UART RX complete callback (ISR context) ────────────────────────── */
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance != USART2)
        return;

    if (rx_phase == 0)
    {
        /* Phase 0: scanning for start byte (1 byte at a time) */
        if (rx_buf[0] == START_RX)
        {
            /* Found 0xAA — receive remaining 18 bytes into rx_buf[1..18] */
            rx_phase = 1;
            HAL_UART_Receive_IT(&huart2, &rx_buf[1], RX_FRAME_SIZE - 1);
        }
        else
        {
            /* Not a start byte — keep scanning */
            HAL_UART_Receive_IT(&huart2, &rx_buf[0], 1);
        }
        return;
    }

    /* Phase 1: full payload received — validate and process */
    rx_phase = 0;

    /* Validate CRC (bytes 1..17, CRC in byte 18) */
    uint8_t crc = crc8_xor(&rx_buf[1], RX_FRAME_SIZE - 2);
    if (crc == rx_buf[RX_FRAME_SIZE - 1])
    {
        process_frame();
    }

    /* Back to scanning for next start byte */
    HAL_UART_Receive_IT(&huart2, &rx_buf[0], 1);
}

/* ── Send 23-byte status report to Pi ───────────────────────────────── */
void sendStatusReport(void)
{
    uint8_t tx_buf[TX_FRAME_SIZE];

    tx_buf[0] = START_TX;

    uint8_t flags = 0;
    if (motors[0]->active_movement_flag) flags |= FLAG_M1_MOVING;
    if (motors[1]->active_movement_flag) flags |= FLAG_M2_MOVING;
    if (motors[2]->active_movement_flag) flags |= FLAG_M3_MOVING;
    if (motors[3]->active_movement_flag) flags |= FLAG_M4_MOVING;
    if (motors[4]->active_movement_flag) flags |= FLAG_M5_MOVING;
    if (motors[4]->stallguard.stall_flag) flags |= FLAG_M5_STALL;
    if (homing_done_flag)                 flags |= FLAG_HOMING_DONE;
    if (error_flag)                       flags |= FLAG_ERROR;
    tx_buf[1] = flags;

    pack_int32(&tx_buf[2],  motors[0]->motion.position);
    pack_int32(&tx_buf[6],  motors[1]->motion.position);
    pack_int32(&tx_buf[10], motors[2]->motion.position);
    pack_int32(&tx_buf[14], motors[3]->motion.position);
    pack_int32(&tx_buf[18], motors[4]->motion.position);

    tx_buf[TX_FRAME_SIZE - 1] = crc8_xor(&tx_buf[1], TX_FRAME_SIZE - 2);

    HAL_UART_Transmit(&huart2, tx_buf, TX_FRAME_SIZE, 50);
}

/* ── Start listening for serial commands ────────────────────────────── */
void startSerialReceive(void)
{
    rx_phase = 0;
    HAL_UART_Receive_IT(&huart2, &rx_buf[0], 1);  /* Start byte-by-byte scan */
}