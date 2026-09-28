# ADR-016 — Lambda disparada por ObjectCreated en el bucket `raw`.

data "archive_file" "s3_event_handler" {
  type        = "zip"
  source_file = "${path.module}/lambda/s3_event_handler.py"
  output_path = "${path.module}/lambda/s3_event_handler.zip"
}

resource "aws_iam_role" "lambda_s3_event" {
  name = "${var.project_prefix}-lambda-s3-event-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic_logs" {
  role       = aws_iam_role.lambda_s3_event.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_s3_read" {
  name = "${var.project_prefix}-lambda-s3-read"
  role = aws_iam_role.lambda_s3_event.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket"]
      Resource = [aws_s3_bucket.data_lake["raw"].arn, "${aws_s3_bucket.data_lake["raw"].arn}/*"]
    }]
  })
}

resource "aws_lambda_function" "s3_event_handler" {
  function_name    = "${var.project_prefix}-s3-raw-event-handler"
  role             = aws_iam_role.lambda_s3_event.arn
  handler          = "s3_event_handler.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.s3_event_handler.output_path
  source_code_hash = data.archive_file.s3_event_handler.output_base64sha256
  timeout          = 30
  memory_size      = 128
}

resource "aws_lambda_permission" "allow_s3" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.s3_event_handler.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.data_lake["raw"].arn
}

resource "aws_s3_bucket_notification" "raw_bucket_notification" {
  bucket = aws_s3_bucket.data_lake["raw"].id

  lambda_function {
    lambda_function_arn = aws_lambda_function.s3_event_handler.arn
    events              = ["s3:ObjectCreated:*"]
  }

  depends_on = [aws_lambda_permission.allow_s3]
}
